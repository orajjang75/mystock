"""Saving alerts: fields, cooldown, latency log, delivery to outside channels, reading."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.market import KST
from app.db.enums import BarLength, Market
from app.db.models import Alert, Instrument
from app.services import alerts as svc
from app.services.alert_engine import AlertDraft
from app.services.notifier import Notification, Notifier, NotifierError

D = Decimal


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


def as_kst(stamp: datetime) -> datetime:
    """SQLite hands back the KST wall time without a zone; PostgreSQL an aware value."""
    return stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp.astimezone(KST)


def draft(
    kind: str = "sell",
    code: str = "900010",
    bar: str = "2026-10-16 10:00",
    length: BarLength | None = BarLength.M60,
    **kwargs: object,
) -> AlertDraft:
    bar_time = at(bar)
    minutes = {BarLength.M30: 30, BarLength.M60: 60, BarLength.D1: 930, None: 0}[length]
    return AlertDraft(
        kind=kind,
        holding_id=None,
        code=code,
        bar_time=bar_time,
        bar_length=length,
        bar_end=bar_time + timedelta(minutes=minutes) if length else None,
        **kwargs,  # type: ignore[arg-type]
    )


def save(
    session: Session,
    drafts: list[AlertDraft],
    created: str = "2026-10-16 11:00:10",
    cooldown: int = 6,
    notifiers: list[Notifier] | None = None,
) -> svc.SaveResult:
    return svc.save_drafts(
        session,
        drafts,
        created_at=at(created),
        cooldown_bars=cooldown,
        signal_length=BarLength.M60,
        notifiers=notifiers or [],
    )


@pytest.fixture(autouse=True)
def stocks(session: Session) -> None:
    session.add_all(
        [
            Instrument(code="900010", name="모의KOSPI001", market=Market.KOSPI),
            Instrument(code="900020", name="모의KOSPI002", market=Market.KOSPI),
        ]
    )
    session.flush()


class Recorder(Notifier):
    name = "recorder"

    def __init__(self, fail: bool = False) -> None:
        self.texts: list[str] = []
        self.fail = fail

    def send(self, notification: Notification) -> None:
        if self.fail:
            raise NotifierError("recorder is down")
        self.texts.append(notification.text)


# --- saving -------------------------------------------------------------------------------------


def test_an_alert_is_stored_with_its_evidence_and_parameters(session: Session) -> None:
    result = save(
        session,
        [
            draft(
                suggested_quantity=33,
                price=67_405.0,
                rebuy_target_price=66_690.5,
                evidence={"signals": ["rsi_overbought_exit"], "rsi": 68.2},
                params={"sell": {"min_overlap": 2}},
            )
        ],
    )

    (alert,) = result.saved
    stored = session.get(Alert, alert.id)
    assert stored is not None
    assert (stored.kind, stored.code, stored.suggested_quantity) == ("sell", "900010", 33)
    assert stored.price == D("67405.0")
    assert stored.rebuy_target_price == D("66690.5")
    assert stored.evidence["rsi"] == 68.2
    assert stored.params == {"sell": {"min_overlap": 2}}
    assert stored.bar_time is not None
    assert stored.is_read is False
    assert stored.delivery == [{"channel": "in_app", "status": "stored"}]
    assert as_kst(stored.occurred_at) == at("2026-10-16 11:00:10")


def test_an_alert_without_a_stock_is_stored_with_no_code(session: Session) -> None:
    (alert,) = save(session, [draft(kind="data_stale", code="", length=None)]).saved

    assert alert.code is None


# --- cooldown (A-10) -----------------------------------------------------------------------------


def test_the_same_signal_on_the_same_stock_is_blocked_for_the_cooldown(session: Session) -> None:
    save(session, [draft(bar="2026-10-16 09:00")])

    for bar, blocked in [
        ("2026-10-16 09:00", True),  # the very same bar
        ("2026-10-16 10:00", True),  # 1 bar later
        ("2026-10-16 14:00", True),  # 5 bars later
        ("2026-10-16 15:00", False),  # 6 bars later
    ]:
        result = save(session, [draft(bar=bar)])
        assert (len(result.saved) == 0) is blocked, bar


def test_a_blocked_signal_is_counted_but_not_stored(session: Session) -> None:
    save(session, [draft(bar="2026-10-16 09:00")])

    result = save(session, [draft(bar="2026-10-16 10:00")])

    assert (result.saved, result.suppressed) == ([], 1)
    assert session.scalar(select(func.count()).select_from(Alert)) == 1


def test_the_cooldown_is_per_stock_and_per_kind(session: Session) -> None:
    save(session, [draft("sell", "900010", bar="2026-10-16 09:00")])

    result = save(
        session,
        [
            draft("sell", "900020", bar="2026-10-16 10:00"),  # another stock
            draft("rebuy", "900010", bar="2026-10-16 10:00"),  # another signal
        ],
    )

    assert len(result.saved) == 2


def test_the_night_does_not_count_towards_the_cooldown(session: Session) -> None:
    save(session, [draft(bar="2026-10-16 14:00")], cooldown=6)  # Friday 14:00

    # Monday 09:00 is only 2 bars later, 12:00 is 5, 13:00 is the 6th
    for bar, blocked in [
        ("2026-10-19 09:00", True),
        ("2026-10-19 12:00", True),
        ("2026-10-19 13:00", False),
    ]:
        assert (len(save(session, [draft(bar=bar)]).saved) == 0) is blocked, bar


def test_the_cooldown_counts_bars_of_the_signal_length(session: Session) -> None:
    save(session, [draft(bar="2026-10-16 09:00", length=BarLength.M30)], cooldown=6)

    blocked = save(session, [draft(bar="2026-10-16 11:30", length=BarLength.M30)], cooldown=6)
    allowed = save(session, [draft(bar="2026-10-16 12:00", length=BarLength.M30)], cooldown=6)

    assert (len(blocked.saved), len(allowed.saved)) == (0, 1)  # 5 and 6 half-hours later


def test_with_the_cooldown_switched_off_each_bar_alerts_but_never_twice(session: Session) -> None:
    bars = ["2026-10-16 09:00", "2026-10-16 09:00", "2026-10-16 10:00", "2026-10-16 10:00"]
    results = [save(session, [draft(bar=bar)], cooldown=0) for bar in bars]

    assert [len(r.saved) for r in results] == [1, 0, 1, 0]


def test_a_longer_cooldown_blocks_longer(session: Session) -> None:
    save(session, [draft(bar="2026-10-16 09:00")], cooldown=2)

    assert len(save(session, [draft(bar="2026-10-16 10:00")], cooldown=2).saved) == 0
    assert len(save(session, [draft(bar="2026-10-16 11:00")], cooldown=2).saved) == 1


def test_daily_alerts_only_block_the_same_day(session: Session) -> None:
    def daily(day: str) -> AlertDraft:
        return draft("force_sell", bar=f"{day} 00:00", length=None)

    save(session, [daily("2026-10-15")])

    assert len(save(session, [daily("2026-10-15")]).saved) == 0
    assert len(save(session, [daily("2026-10-16")]).saved) == 1  # the next trading day


def test_the_stale_data_warning_is_rate_limited_like_other_alerts(session: Session) -> None:
    def stale(bar: str) -> AlertDraft:
        return draft("data_stale", "", bar=bar, length=None)

    save(session, [stale("2026-10-16 10:30")])

    # counted in 60-minute bars of the configured signal length
    assert len(save(session, [stale("2026-10-16 11:00")]).saved) == 0  # 1 bar later
    assert len(save(session, [stale("2026-10-16 15:00")]).saved) == 0  # 5 bars later
    assert len(save(session, [stale("2026-10-19 09:30")]).saved) == 1  # 6 bars later: Monday


# --- latency log -------------------------------------------------------------------------------


def test_the_delay_from_the_bar_close_is_logged_and_stored(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    (alert,) = save(session, [draft(bar="2026-10-16 10:00")], created="2026-10-16 11:00:12").saved

    record = next(r for r in caplog.records if "alert latency" in r.getMessage())
    assert record.levelno == logging.INFO
    assert "latency=12.0s" in record.getMessage()
    assert "bar_end=2026-10-16T11:00:00+09:00" in record.getMessage()
    assert "created_at=2026-10-16T11:00:12+09:00" in record.getMessage()
    assert alert.evidence["latency_seconds"] == 12.0
    assert alert.evidence["bar_end"].startswith("2026-10-16T11:00:00")


def test_a_late_alert_is_a_warning(session: Session, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    save(session, [draft(bar="2026-10-16 10:00")], created="2026-10-16 11:01:30")

    record = next(r for r in caplog.records if "alert latency" in r.getMessage())
    assert record.levelno == logging.WARNING
    assert "EXCEEDED" in record.getMessage()
    assert "latency=90.0s" in record.getMessage()


def test_exactly_one_minute_is_still_within_the_target(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    save(session, [draft(bar="2026-10-16 10:00")], created="2026-10-16 11:01:00")

    record = next(r for r in caplog.records if "alert latency" in r.getMessage())
    assert record.levelno == logging.INFO


def test_daily_and_barless_alerts_are_not_measured(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    save(
        session,
        [draft("force_sell", length=None), draft("rebuy", code="900020", length=BarLength.D1)],
    )

    assert "alert latency" not in caplog.text


# --- outside channels ---------------------------------------------------------------------------


def test_every_saved_alert_is_sent_and_the_result_is_kept(session: Session) -> None:
    recorder = Recorder()

    (alert,) = save(
        session,
        [draft(suggested_quantity=33, price=67_405.0, rebuy_target_price=66_690.4)],
        notifiers=[recorder],
    ).saved

    assert alert.delivery[0] == {"channel": "in_app", "status": "stored"}
    assert alert.delivery[1]["channel"] == "recorder"
    assert alert.delivery[1]["status"] == "sent"
    assert len(recorder.texts) == 1


def test_the_message_is_a_summary_only(session: Session) -> None:
    recorder = Recorder()

    save(
        session,
        [
            draft(
                suggested_quantity=1234,
                price=67_405.0,
                rebuy_target_price=66_690.4,
                evidence={"rsi": 68.2, "signals": ["rsi_overbought_exit"], "secret_ratio": 0.42},
                params={"sell": {"min_overlap": 2}},
            )
        ],
        notifiers=[recorder],
    )

    (text,) = recorder.texts
    assert text.splitlines() == [
        "[매도 신호] 모의KOSPI001 (900010)",
        "제안 수량: 1,234주",
        "현재가: 67,405원",
        "재매수 목표가: 66,690원",
    ]
    assert "68.2" not in text and "0.42" not in text and "min_overlap" not in text


def test_a_failing_channel_does_not_lose_the_alert(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    broken, working = Recorder(fail=True), Recorder()

    (alert,) = save(session, [draft()], notifiers=[broken, working]).saved

    statuses = {d["channel"]: d for d in alert.delivery}
    assert statuses["recorder"]["status"] in {"failed", "sent"}
    assert [d["status"] for d in alert.delivery[1:]] == ["failed", "sent"]
    assert alert.delivery[1]["error"] == "recorder is down"
    assert len(working.texts) == 1
    assert session.get(Alert, alert.id) is not None
    assert "failed" in caplog.text


def test_a_suppressed_alert_is_not_sent(session: Session) -> None:
    recorder = Recorder()
    save(session, [draft(bar="2026-10-16 09:00")], notifiers=[recorder])

    save(session, [draft(bar="2026-10-16 10:00")], notifiers=[recorder])

    assert len(recorder.texts) == 1


def test_the_message_formats() -> None:
    assert svc.format_message(
        "rebuy", "삼성", "005930", quantity=31, price=95_000.0, target=98_790.0
    ) == ("[재매수 신호] 삼성 (005930)\n제안 수량: 31주\n현재가: 95,000원\n재매수 목표가: 98,790원")
    assert svc.format_message("data_stale", None, None, note="분봉 수집 지연") == (
        "[시세 갱신 지연 경고]\n분봉 수집 지연"
    )
    assert (
        svc.format_message("force_sell", "삼성", "005930")
        == "[강제 매도 (5일선 이탈)] 삼성 (005930)"
    )


def test_a_test_message_reports_each_channel(session: Session) -> None:
    outcomes = svc.send_test([Recorder(), Recorder(fail=True)])

    assert outcomes == [
        {"channel": "recorder", "status": "sent"},
        {"channel": "recorder", "status": "failed", "error": "recorder is down"},
    ]


# --- reading ------------------------------------------------------------------------------------


def seed(session: Session) -> list[Alert]:
    drafts = [
        draft("sell", "900010", "2026-10-16 09:00"),
        draft("rebuy", "900010", "2026-10-16 10:00"),
        draft("sell", "900020", "2026-10-16 11:00"),
        draft("stop_loss", "900020", "2026-10-16 12:00"),
    ]
    saved = []
    for i, d in enumerate(drafts):  # created one minute apart so the order is clear
        saved += save(session, [d], created=f"2026-10-16 1{i}:00:10").saved
    return saved


def test_alerts_are_listed_newest_first(session: Session) -> None:
    seed(session)

    assert [a.kind for a in svc.list_alerts(session)] == ["stop_loss", "sell", "rebuy", "sell"]


def test_alerts_can_be_filtered_by_kind_code_and_read_state(session: Session) -> None:
    first, *_ = seed(session)
    svc.mark_read(session, first.id)

    assert [a.code for a in svc.list_alerts(session, kind="sell")] == ["900020", "900010"]
    assert {a.kind for a in svc.list_alerts(session, code="900020")} == {"sell", "stop_loss"}
    assert first.id not in [a.id for a in svc.list_alerts(session, unread_only=True)]
    assert len(svc.list_alerts(session, unread_only=True)) == 3


def test_paging(session: Session) -> None:
    seed(session)

    assert len(svc.list_alerts(session, limit=2)) == 2
    assert [a.kind for a in svc.list_alerts(session, limit=2, offset=2)] == ["rebuy", "sell"]


def test_marking_read_is_idempotent_and_updates_the_count(session: Session) -> None:
    first, second, *_ = seed(session)

    assert svc.unread_count(session) == 4
    svc.mark_read(session, first.id)
    svc.mark_read(session, first.id)
    svc.mark_read(session, second.id)

    assert svc.unread_count(session) == 2
    assert svc.mark_read(session, 99999) is None


def test_warnings_are_told_apart_from_signals() -> None:
    assert svc.level_of("sell") == "signal"
    assert svc.level_of("force_sell") == "signal"
    for kind in ("rebuy_held", "reduce_position", "stop_loss", "data_stale"):
        assert svc.level_of(kind) == "warning"
