"""The run log and the 모의 운영 report, on a mock market driven bar by bar by a mock clock."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import JobRun
from app.jobs import ops_report
from app.jobs.monitor import run_daily_job, run_intraday_job, run_logged
from app.services import ops
from tests.jobs.test_monitor import BAR_CLOSES, World, at, world  # the fixture

DAY = date(2026, 10, 16)


def tick(w: World, hhmm: str, *, seconds: int = 10) -> None:
    """What the scheduler does at a bar close: run the job, logged."""
    w.clock.now = at(f"2026-10-16 {hhmm}") + timedelta(seconds=seconds)
    run_logged(w.ctx, "intraday", run_intraday_job)


def full_day(w: World, skip: tuple[str, ...] = ()) -> None:
    w.configure(cooldown=1)
    for hhmm in ["09:00", *BAR_CLOSES]:  # the scheduler also fires at 09:00; the job skips it
        if hhmm not in skip:
            tick(w, hhmm)
    w.clock.now = at("2026-10-16 18:00:10")
    run_logged(w.ctx, "daily", run_daily_job)


def report(w: World) -> ops.DayReport:
    with w.session() as session:
        return ops.day_report(session, DAY)


def test_a_clean_day_has_every_bar_close_seen_every_bar_stored_and_every_alert_on_time(
    world: World,
) -> None:
    full_day(world)

    r = report(world)

    assert r.trading_day and len(r.intraday) == 13
    assert [t.outcome for t in r.intraday] == ["ok"] * 13
    assert (r.gaps, r.collection_failures) == (0, 0)
    assert r.daily is not None and r.daily.outcome == "ok"
    assert (r.holdings, r.bars_expected, r.bars_stored, r.bar_coverage) == (1, 13, 13, 1.0)
    assert r.alerts == {"sell": 13}
    assert r.latencies == [10.0] * 13
    assert (r.percentile(0.5), r.percentile(0.95), r.within_target) == (10.0, 10.0, 1.0)
    assert r.late == [] and r.clean


def test_the_log_has_one_row_per_run_with_its_bar_and_what_it_did(world: World) -> None:
    world.configure(cooldown=1)

    tick(world, "09:00")  # before the first bar has closed: skipped
    tick(world, "09:30")

    with world.session() as session:
        skipped, ok = session.scalars(select(JobRun).order_by(JobRun.id)).all()
    assert (skipped.outcome, skipped.detail["skipped"]) == ("skipped", "outside market hours")
    assert (ok.job, ok.outcome) == ("intraday", "ok")
    assert ok.scheduled_for.astimezone(at("2026-10-16 09:30").tzinfo).strftime("%H:%M") == "09:30"
    assert ok.detail["saved"] == 1 and ok.detail["collected"] is True
    assert (ok.finished_at - ok.started_at).total_seconds() >= 0


def test_a_bar_close_without_a_run_is_a_gap(world: World) -> None:
    full_day(world, skip=("11:00",))

    r = report(world)

    assert r.count("missing") == 1 and r.gaps == 1
    assert [t.at for t in r.intraday if t.outcome == "missing"] == ["11:00"]
    assert not r.clean


def test_a_cut_feed_shows_as_stale_runs_with_the_error_and_missing_bars(world: World) -> None:
    world.configure(cooldown=1)
    for hhmm in ("09:30", "10:00"):
        tick(world, hhmm)
    world.adapter.cut = True
    for hhmm in ("10:30", "11:00", "11:30"):
        tick(world, hhmm)
    world.adapter.cut = False
    for hhmm in BAR_CLOSES[5:]:  # the feed is back for the rest of the day
        tick(world, hhmm)

    r = report(world)

    assert [t.outcome for t in r.intraday[:6]] == ["ok", "ok", "stale", "stale", "stale", "ok"]
    assert r.gaps == 3 and r.collection_failures == 3
    assert "ConnectionError" in r.failures[0] and r.failures[0].startswith("10:30")
    assert r.stale_alerts >= 1  # the 시세 갱신 지연 경고
    assert not r.clean
    stale = world.session().scalars(select(JobRun).where(JobRun.outcome == "stale")).first()
    assert stale is not None and "ConnectionError" in stale.detail["error"]


def test_a_run_that_raises_is_logged_as_failed_and_the_error_still_propagates(world: World) -> None:
    def broken(_ctx: object) -> object:
        raise RuntimeError("boom")

    world.clock.now = at("2026-10-16 10:00:10")

    with pytest.raises(RuntimeError, match="boom"):
        run_logged(world.ctx, "intraday", broken)  # type: ignore[arg-type]

    run = report(world).intraday[1]
    assert (run.at, run.outcome) == ("10:00", "failed") and "boom" in run.detail


def test_an_alert_later_than_a_minute_is_listed_and_fails_the_day(world: World) -> None:
    world.configure(cooldown=1)
    tick(world, "09:30", seconds=10)
    tick(world, "10:00", seconds=95)  # the job started 95 s after the bar closed

    r = report(world)

    assert r.latencies == [10.0, 95.0]
    assert r.within_target == 0.5 and r.percentile(1.0) == 95.0
    assert [(x["kind"], x["seconds"]) for x in r.late] == [("sell", 95.0)]


def test_the_log_failing_to_write_never_fails_the_job(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.configure(cooldown=1)

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(ops, "record_run", broken)
    world.clock.now = at("2026-10-16 09:30:10")

    result = run_logged(world.ctx, "intraday", run_intraday_job)

    assert result.saved == 1


def test_a_holiday_has_nothing_to_miss(world: World) -> None:
    with world.session() as session:
        r = ops.day_report(session, date(2026, 10, 17))  # a Saturday

    assert not r.trading_day and r.intraday == [] and r.clean


def test_the_period_report_adds_up_the_gate_numbers_and_renders_them(world: World) -> None:
    full_day(world, skip=("11:00",))
    with world.session() as session:
        data = ops.period_report(session, date(2026, 10, 15), date(2026, 10, 17))

    totals = data["totals"]
    assert totals["trading_days"] == 2  # Thursday and Friday; Saturday is closed
    assert (
        totals["expected_ticks"],
        totals["ok_ticks"],
        totals["gaps"],
        totals["missing_ticks"],
    ) == (26, 12, 14, 14)
    assert totals["latency_p95"] == 10.0 and totals["within_target"] == 1.0
    assert [d["day"] for d in data["days"]] == ["2026-10-15", "2026-10-16", "2026-10-17"]
    json.dumps(data)

    text = ops.render_markdown(data)

    assert text.startswith("# 모의 운영 리포트 2026-10-15 ~ 2026-10-17")
    assert "5단계 게이트 숫자" in text and "신호를 낼 수 없었던 봉" in text
    assert "11:00 missing" in text  # the day that needs a look is listed with its bar
    assert "확인 필요" in text


def test_the_clean_day_reads_as_clean_in_the_text(world: World) -> None:
    full_day(world)
    with world.session() as session:
        text = ops.render_markdown(ops.period_report(session, DAY, DAY))

    assert (
        "| 2026-10-16 | 개장 | 13/13 | 0 | 0 | ok | 100.0% | 13 | 10.0초 | 100.0% | 이상 없음 |"
        in text
    )
    assert "**0회**" in text
    assert "확인이 필요한 날" not in text


# --- API, CLI -------------------------------------------------------------------------------------


def login(client: TestClient) -> TestClient:
    client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
    return client


def test_the_report_endpoint_needs_a_login_and_has_json_and_markdown(world: World) -> None:
    full_day(world)
    client = world.api()

    assert client.get("/api/ops/report").status_code == 401
    login(client)
    data = client.get("/api/ops/report", params={"from": "2026-10-16", "to": "2026-10-16"}).json()
    assert data["totals"]["gaps"] == 0 and data["days"][0]["clean"] is True
    md = client.get(
        "/api/ops/report", params={"from": "2026-10-16", "to": "2026-10-16", "format": "md"}
    )
    assert md.headers["content-type"].startswith("text/markdown")
    assert "5단계 게이트 숫자" in md.text


def test_the_report_period_is_checked(world: World) -> None:
    client = login(world.api())

    assert (
        client.get("/api/ops/report", params={"from": "2026-10-16", "to": "2026-10-01"}).status_code
        == 422
    )
    assert (
        client.get("/api/ops/report", params={"from": "2026-01-01", "to": "2026-10-16"}).status_code
        == 422
    )
    assert client.get("/api/ops/report", params={"format": "xml"}).status_code == 422
    default = client.get("/api/ops/report").json()  # the last 7 days up to the mock "today"
    assert len(default["days"]) == 7


def test_the_cli_prints_and_saves_the_report(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: object,
) -> None:
    full_day(world)
    monkeypatch.setattr(ops_report, "get_sessionmaker", lambda: world.ctx.session_factory)

    assert ops_report.main(["--from", "2026-10-16", "--to", "2026-10-16"]) == 0

    assert "5단계 게이트 숫자" in capsys.readouterr().out
    del tmp_path


# --- 모의 운영: no fills ---------------------------------------------------------------------------


def test_a_paper_run_takes_no_fills_but_still_shows_signals_and_says_so(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = Settings(paper_run=True)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: paper)
    monkeypatch.setattr("app.api.health.get_settings", lambda: paper)
    world.configure(cooldown=1)
    tick(world, "09:30")
    client = login(world.api())

    fill = client.post(
        f"/api/holdings/{world.holding_id}/fills",
        json={"side": "sell", "price": 1000, "quantity": 10},
    )
    retry = client.post(f"/api/holdings/{world.holding_id}/cycles/1/retry")
    abandon = client.post(f"/api/holdings/{world.holding_id}/cycles/1/abandon")

    assert (fill.status_code, retry.status_code, abandon.status_code) == (409, 409, 409)
    assert "모의 운영" in fill.json()["detail"]
    assert client.get("/api/health").json()["mode"] == "paper"
    assert (
        client.get("/api/alerts").json()["items"][0]["kind"] == "sell"
    )  # the signal is still there
    assert client.get("/api/holdings").status_code == 200
    registered = client.post(
        "/api/holdings", json={"code": world.code, "quantity": 5, "avg_price": 100}
    )
    assert registered.status_code == 201  # watching a position is not a trade


def test_a_normal_run_still_takes_fills(world: World) -> None:
    client = login(world.api())

    assert client.get("/api/health").json()["mode"] == "normal"
    ok = client.post(
        f"/api/holdings/{world.holding_id}/fills",
        json={"side": "sell", "price": 1000, "quantity": 10},
    )
    assert ok.status_code == 201
