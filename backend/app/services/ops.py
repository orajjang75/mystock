"""Operations log and the 모의 운영 report (PRD 로드맵 5단계 게이트).

Every scheduled run is written to ``job_runs`` by ``run_logged``. The report reads that log and
the alerts back, one trading day at a time:

- Was every bar close seen? A trading day has 13 intraday bar closes (09:30 ... 15:30) and one
  daily run. A close with no run, a run that failed, or a run that paused the signals because the
  data was stale is a *gap*: no signal could have been made for that bar.
- Was the data complete? Each holding should have all 13 stored 30-minute bars of the day.
- How late were the alerts? Latency = alert time - the bar's close, with the target of one
  minute (PRD 10장 비기능 요구사항).
- What did collection cost? Failed and stale runs, with the error of the last one.

"No missed signal" is judged by the coverage above, not by comparing against a second opinion of
what the signals should have been: the signal code is the same one the backtest verified.
"""

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.market import KST, is_trading_day
from app.db.models import Alert, Holding, JobRun, OhlcvIntraday
from app.services import status as collection_status

LATENCY_TARGET_SECONDS = 60


def bar_closes() -> list[time]:
    """09:30, 10:00 ... 15:30: the thirteen closes of the 30-minute bars of a session."""
    return [time(9 + (30 * (k + 1)) // 60, (30 * (k + 1)) % 60) for k in range(13)]


def floor_30(moment: datetime) -> datetime:
    local = moment.astimezone(KST)
    return local.replace(minute=0 if local.minute < 30 else 30, second=0, microsecond=0)


# --- the log -----------------------------------------------------------------------------------


def record_run(
    session: Session,
    job: str,
    scheduled_for: datetime,
    started: datetime,
    finished: datetime,
    outcome: str,
    detail: dict[str, Any],
) -> JobRun:
    """Add one row. Commits: it is written after the job has finished with its own session."""
    run = JobRun(
        job=job,
        scheduled_for=scheduled_for,
        started_at=started,
        finished_at=finished,
        outcome=outcome,
        detail=detail,
    )
    session.add(run)
    session.commit()
    return run


def last_error(session: Session, source: str) -> str | None:
    return collection_status.load_status(session)[source].last_error


# --- the report --------------------------------------------------------------------------------


@dataclass
class Tick:
    at: str  # "HH:MM"
    outcome: str  # ok | stale | failed | skipped | missing
    detail: str = ""


@dataclass
class DayReport:
    day: date
    trading_day: bool
    intraday: list[Tick] = field(default_factory=list)
    daily: Tick | None = None
    holdings: int = 0
    bars_expected: int = 0
    bars_stored: int = 0
    alerts: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    late: list[dict[str, Any]] = field(default_factory=list)
    stale_alerts: int = 0
    delivery: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    # -- derived -----------------------------------------------------------------------------

    def count(self, outcome: str) -> int:
        return sum(1 for t in self.intraday if t.outcome == outcome)

    @property
    def gaps(self) -> int:
        """Bar closes for which no signal could be made."""
        return sum(1 for t in self.intraday if t.outcome in ("missing", "failed", "stale"))

    @property
    def collection_failures(self) -> int:
        runs = [*self.intraday, *([self.daily] if self.daily else [])]
        return sum(1 for t in runs if t.outcome in ("failed", "stale"))

    @property
    def bar_coverage(self) -> float | None:
        return self.bars_stored / self.bars_expected if self.bars_expected else None

    def percentile(self, q: float) -> float | None:
        if not self.latencies:
            return None
        ordered = sorted(self.latencies)
        return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]

    @property
    def within_target(self) -> float | None:
        if not self.latencies:
            return None
        return sum(1 for x in self.latencies if x <= LATENCY_TARGET_SECONDS) / len(self.latencies)

    @property
    def clean(self) -> bool:
        """The gate for one day: no gap, no failed daily run, every bar stored, nothing late."""
        if not self.trading_day:
            return True
        daily_ok = self.daily is None or self.daily.outcome == "ok"
        coverage = self.bar_coverage
        return (
            self.gaps == 0 and daily_ok and (coverage is None or coverage >= 1.0) and not self.late
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat(),
            "trading_day": self.trading_day,
            "expected_ticks": len(self.intraday),
            "ok": self.count("ok"),
            "stale": self.count("stale"),
            "failed": self.count("failed"),
            "missing": self.count("missing"),
            "skipped": self.count("skipped"),
            "gaps": self.gaps,
            "daily": None
            if self.daily is None
            else {"at": self.daily.at, "outcome": self.daily.outcome, "detail": self.daily.detail},
            "collection_failures": self.collection_failures,
            "holdings": self.holdings,
            "bars_expected": self.bars_expected,
            "bars_stored": self.bars_stored,
            "bar_coverage": self.bar_coverage,
            "alerts": self.alerts,
            "stale_alerts": self.stale_alerts,
            "latency": {
                "n": len(self.latencies),
                "p50": self.percentile(0.5),
                "p95": self.percentile(0.95),
                "max": max(self.latencies) if self.latencies else None,
                "within_target": self.within_target,
                "target_seconds": LATENCY_TARGET_SECONDS,
            },
            "late": self.late,
            "delivery": self.delivery,
            "failures": self.failures,
            "ticks": [
                {"at": t.at, "outcome": t.outcome, "detail": t.detail} for t in self.intraday
            ],
            "clean": self.clean,
        }


def _local(stamp: datetime) -> datetime:
    return stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp.astimezone(KST)


def day_report(session: Session, day: date) -> DayReport:
    """What happened on ``day`` according to the run log, the stored bars and the alerts."""
    report = DayReport(day=day, trading_day=is_trading_day(day))
    start = datetime.combine(day, time.min, tzinfo=KST)
    end = start + timedelta(days=1)

    runs = list(
        session.scalars(
            select(JobRun)
            .where(JobRun.scheduled_for >= start, JobRun.scheduled_for < end)
            .order_by(JobRun.id)
        )
    )
    alerts = list(
        session.scalars(select(Alert).where(Alert.occurred_at >= start, Alert.occurred_at < end))
    )
    for alert in alerts:
        report.alerts[alert.kind] = report.alerts.get(alert.kind, 0) + 1
        if alert.kind == "data_stale":
            report.stale_alerts += 1
        latency = alert.evidence.get("latency_seconds")
        if isinstance(latency, int | float):
            report.latencies.append(float(latency))
            if latency > LATENCY_TARGET_SECONDS:
                report.late.append(
                    {
                        "kind": alert.kind,
                        "code": alert.code,
                        "seconds": float(latency),
                        "bar_end": alert.evidence.get("bar_end"),
                    }
                )
        for entry in alert.delivery:
            key = f"{entry.get('channel')}:{entry.get('status')}"
            if entry.get("channel") != "in_app":
                report.delivery[key] = report.delivery.get(key, 0) + 1

    if not report.trading_day:
        return report

    by_tick: dict[str, JobRun] = {}
    for run in runs:
        if run.job == "intraday":
            by_tick[_local(run.scheduled_for).strftime("%H:%M")] = (
                run  # the latest run of a tick wins
            )
        elif run.job == "daily":
            report.daily = Tick(
                _local(run.scheduled_for).strftime("%H:%M"),
                run.outcome,
                str(run.detail.get("error") or run.detail.get("skipped") or ""),
            )
    for close in bar_closes():
        key = close.strftime("%H:%M")
        tick = by_tick.get(key)
        if tick is None:
            report.intraday.append(Tick(key, "missing", "작업이 실행되지 않았습니다"))
            continue
        why = str(
            tick.detail.get("error")
            or tick.detail.get("skipped")
            or ",".join(tick.detail.get("stale") or [])
        )
        report.intraday.append(Tick(key, tick.outcome, why))
        if tick.outcome in ("stale", "failed") and tick.detail.get("error"):
            report.failures.append(f"{key} {tick.detail['error']}")
    if report.daily and report.daily.outcome in ("stale", "failed") and report.daily.detail:
        report.failures.append(f"{report.daily.at} {report.daily.detail}")

    codes = list(session.scalars(select(Holding.code).distinct()))
    report.holdings = len(codes)
    report.bars_expected = len(codes) * len(bar_closes())
    if codes:
        report.bars_stored = int(
            session.scalar(
                select(func.count())
                .select_from(OhlcvIntraday)
                .where(
                    OhlcvIntraday.code.in_(codes),
                    OhlcvIntraday.bar_time >= start,
                    OhlcvIntraday.bar_time < end,
                )
            )
            or 0
        )
    return report


def period_report(session: Session, first: date, last: date) -> dict[str, Any]:
    """Day reports over a period, and the numbers the 5단계 gate is read from."""
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    reports = [day_report(session, d) for d in days]
    trading = [r for r in reports if r.trading_day]
    latencies = [x for r in trading for x in r.latencies]
    ticks = sum(len(r.intraday) for r in trading)
    ordered = sorted(latencies)
    stored = sum(r.bars_stored for r in trading)
    expected = sum(r.bars_expected for r in trading)
    totals = {
        "trading_days": len(trading),
        "clean_days": sum(1 for r in trading if r.clean),
        "expected_ticks": ticks,
        "ok_ticks": sum(r.count("ok") for r in trading),
        "gaps": sum(r.gaps for r in trading),
        "missing_ticks": sum(r.count("missing") for r in trading),
        "collection_failures": sum(r.collection_failures for r in trading),
        "stale_alerts": sum(r.stale_alerts for r in trading),
        "bars_expected": expected,
        "bars_stored": stored,
        "bar_coverage": stored / expected if expected else None,
        "alerts": sum(sum(r.alerts.values()) for r in trading),
        "latency_n": len(latencies),
        "latency_p50": statistics.median(ordered) if ordered else None,
        "latency_p95": ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        if ordered
        else None,
        "latency_max": max(ordered) if ordered else None,
        "within_target": sum(1 for x in ordered if x <= LATENCY_TARGET_SECONDS) / len(ordered)
        if ordered
        else None,
        "late_alerts": sum(len(r.late) for r in trading),
    }
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "totals": totals,
        "days": [r.as_dict() for r in reports],
    }


def render_markdown(report: dict[str, Any]) -> str:
    """The period report as text, with the gate numbers first."""
    t = report["totals"]

    def pct(value: float | None, digits: int = 1) -> str:
        return "-" if value is None else f"{100 * value:.{digits}f}%"

    def sec(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}초"

    lines = [
        f"# 모의 운영 리포트 {report['from']} ~ {report['to']}",
        "",
        "실제 시세로 신호만 내고 체결 기록은 받지 않는 운영의 일별 요약입니다.",
        "",
        "## 5단계 게이트 숫자",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 거래일 / 이상 없는 날 | {t['trading_days']}일 / {t['clean_days']}일 |",
        f"| 봉 마감 확인 (기대 → 정상 실행) | {t['expected_ticks']}회 → {t['ok_ticks']}회 |",
        f"| **신호를 낼 수 없었던 봉 (누락·실패·시세 지연)** | **{t['gaps']}회** (작업 미실행 {t['missing_ticks']}회) |",
        f"| 수집 실패·지연 횟수 | {t['collection_failures']}회 (시세 갱신 지연 경고 알림 {t['stale_alerts']}건) |",
        f"| 보유 종목 30분봉 저장률 | {pct(t['bar_coverage'])} ({t['bars_stored']} / {t['bars_expected']}) |",
        f"| 알림 수 | {t['alerts']}건 |",
        f"| 봉 마감 후 알림 지연 p50 / p95 / 최대 | {sec(t['latency_p50'])} / {sec(t['latency_p95'])} / {sec(t['latency_max'])} (표본 {t['latency_n']}건) |",
        f"| 1분 이내 알림 비율 (목표 {LATENCY_TARGET_SECONDS}초) | {pct(t['within_target'])}, 초과 {t['late_alerts']}건 |",
        "",
        "## 일별",
        "",
        "| 날짜 | 거래일 | 정상 | 지연·실패 | 미실행 | 일봉 작업 | 저장률 | 알림 | 지연 p95 | 1분 이내 | 판정 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in report["days"]:
        if not d["trading_day"]:
            lines.append(
                f"| {d['day']} | 휴장 | - | - | - | - | - | {sum(d['alerts'].values())} | - | - | - |"
            )
            continue
        daily = d["daily"]["outcome"] if d["daily"] else "미실행"
        lines.append(
            f"| {d['day']} | 개장 | {d['ok']}/{d['expected_ticks']} | {d['stale'] + d['failed']} | {d['missing']} | {daily} "
            f"| {pct(d['bar_coverage'])} | {sum(d['alerts'].values())} | {sec(d['latency']['p95'])} | {pct(d['latency']['within_target'])} "
            f"| {'이상 없음' if d['clean'] else '확인 필요'} |"
        )
    problems = [d for d in report["days"] if d["trading_day"] and not d["clean"]]
    if problems:
        lines += ["", "## 확인이 필요한 날", ""]
        for d in problems:
            lines.append(f"### {d['day']}")
            lines.append("")
            bad = [tk for tk in d["ticks"] if tk["outcome"] in ("missing", "failed", "stale")]
            for tk in bad:
                lines.append(f"- {tk['at']} {tk['outcome']}: {tk['detail']}")
            if d["daily"] and d["daily"]["outcome"] != "ok":
                lines.append(
                    f"- 일봉 작업 {d['daily']['at']} {d['daily']['outcome']}: {d['daily']['detail']}"
                )
            if d["bar_coverage"] is not None and d["bar_coverage"] < 1:
                lines.append(f"- 30분봉 저장 {d['bars_stored']} / {d['bars_expected']}")
            for late in d["late"]:
                lines.append(
                    f"- 알림 지연 {late['seconds']:.0f}초: {late['kind']} {late['code']} (봉 마감 {late['bar_end']})"
                )
            lines.append("")
    if any(d["delivery"] for d in report["days"]):
        total: dict[str, int] = {}
        for d in report["days"]:
            for key, n in d["delivery"].items():
                total[key] = total.get(key, 0) + n
        lines += ["", "## 앱 밖 알림 전달 결과", ""] + [
            f"- {key}: {n}건" for key, n in sorted(total.items())
        ]
    lines.append("")
    return "\n".join(lines)
