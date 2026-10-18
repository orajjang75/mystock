"""The scheduled jobs driven by a mock clock, bar by bar through a trading day.

The mock market has a full Friday (2026-10-16) of 30-minute bars. The jobs only see the bars
that are confirmed at the simulated time, so stepping the clock forward replays the day.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.mock import MockAdapter, Scenario
from app.api.deps import current_time
from app.core.config import Settings, get_settings
from app.core.market import KST
from app.db.enums import BarLength, FillSide, Market
from app.db.models import Alert, Holding, InvestorFlowDaily, OhlcvIntraday
from app.db.session import get_db
from app.engine.holding_rules import daily_downtrend
from app.jobs.monitor import JobContext, JobResult, run_daily_job, run_intraday_job
from app.main import create_app
from app.services import alert_engine as engine
from app.services import holdings as holdings_service
from app.services.alert_engine import load_daily_context
from app.services.settings import (
    save_alert_cooldown_bars,
    save_channels,
    save_signal_bar_length,
)
from app.services.universe import UniverseSpec, load_universe
from tests.alert_helpers import SELL_FUNCTIONS, force_sell_frame, pin
from tests.conftest import END_DATE, sqlite_engine

TOKEN = "123456789:AAH-test-bot-token"
SMALL = UniverseSpec(kospi_top=20, kosdaq_top=5)
BAR_CLOSES = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)][1:]  # 09:30 .. 15:30


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


class Clock:
    """The simulated time. Calling it returns the current simulated moment."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class CuttableAdapter(MockAdapter):
    """A mock market whose feed can be cut, like a broker API going down."""

    cut = False

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> Any:
        if self.cut:
            password = get_settings().app_password.get_secret_value()
            raise ConnectionError(f"broker unreachable (credentials {password})")
        return super().fetch_intraday_30m(code, start, end)

    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> Any:
        if self.cut:
            raise ConnectionError("exchange feed unreachable")
        return super().fetch_listings(as_of, limit_per_market=limit_per_market)


@dataclass
class World:
    ctx: JobContext
    adapter: CuttableAdapter
    clock: Clock
    code: str
    holding_id: int
    telegram: list[dict[str, Any]] = field(default_factory=list)
    telegram_state: dict[str, int] = field(default_factory=dict)

    def session(self) -> Session:
        return self.ctx.session_factory()

    def tick(self, hhmm: str, day: str = "2026-10-16") -> JobResult:
        """Move the clock to ten seconds after a bar closes and run the intraday job."""
        self.clock.now = at(f"{day} {hhmm}:10")
        return run_intraday_job(self.ctx)

    def alerts(self, kind: str | None = None) -> list[Alert]:
        with self.session() as session:
            query = select(Alert).order_by(Alert.id)
            if kind:
                query = query.where(Alert.kind == kind)
            return list(session.scalars(query))

    def configure(self, *, cooldown: int, length: BarLength = BarLength.M30) -> None:
        with self.session() as session:
            save_alert_cooldown_bars(session, cooldown)
            save_signal_bar_length(session, length)
            save_channels(session, {"telegram": True})
            session.commit()

    def api(self) -> TestClient:
        app = create_app()

        def override_db() -> Iterator[Session]:
            with self.session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_time] = self.clock
        return TestClient(app)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    adapter = CuttableAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    factory = sessionmaker(bind=sqlite_engine(), expire_on_commit=False)
    clock = Clock(at("2026-10-15 18:00:10"))
    telegram: list[dict[str, Any]] = []
    state = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        telegram.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(state["status"], json={"ok": state["status"] == 200})

    settings = Settings(telegram_bot_token=TOKEN, telegram_chat_id="42")
    ctx = JobContext(
        factory, adapter, settings, clock=clock,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), spec=SMALL,
    )  # fmt: skip
    # The evening before: the daily job brings in the universe and its history.
    assert run_daily_job(ctx).skipped is None

    with factory() as session:
        code = next(
            m.code
            for m in load_universe(session)
            if adapter.stock(m.code).scenario is Scenario.UPTREND
            and not daily_downtrend(
                load_daily_context(session, m.code, at("2026-10-16 09:30")).bars["close"]
            ).iloc[-1]
        )
        holding = holdings_service.register(session, code, 100, 1)  # type: ignore[arg-type]
        session.commit()
        holding_id = holding.id

    pin(monkeypatch, true=set(SELL_FUNCTIONS))
    monkeypatch.setattr(engine, "force_sell", force_sell_frame())
    result = World(ctx, adapter, clock, code, holding_id, telegram)

    result.telegram_state = state
    return result


# --- a day of bars ---------------------------------------------------------------------------


def test_the_setup_left_fresh_daily_data_and_a_holding(world: World) -> None:
    assert world.alerts() == []
    with world.session() as session:
        assert session.scalar(select(func.count()).select_from(Holding)) == 1


def test_an_alert_is_created_at_every_bar_close(world: World) -> None:
    world.configure(cooldown=1)  # no cooldown beyond "never the same bar twice"

    results = [world.tick(hhmm) for hhmm in BAR_CLOSES]

    assert len(BAR_CLOSES) == 13
    assert [r.saved for r in results] == [1] * 13
    assert all(r.collected and r.stale == [] for r in results)
    sells = world.alerts("sell")
    assert len(sells) == 13
    bar_starts = [a.bar_time for a in sells]
    assert len(set(bar_starts)) == 13  # one alert per distinct bar
    assert all(a.code == world.code and a.holding_id == world.holding_id for a in sells)


def test_each_alert_is_made_within_a_minute_of_its_bar_closing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.configure(cooldown=1)
    caplog.set_level(logging.INFO)

    for hhmm in BAR_CLOSES:
        world.tick(hhmm)

    latencies = [a.evidence["latency_seconds"] for a in world.alerts("sell")]
    assert latencies == [10.0] * 13
    lines = [r for r in caplog.records if "alert latency" in r.getMessage()]
    assert len(lines) == 13
    assert all(r.levelno == logging.INFO for r in lines)
    assert "bar_end=2026-10-16T09:30:00+09:00" in lines[0].getMessage()
    assert "created_at=2026-10-16T09:30:10+09:00" in lines[0].getMessage()


def test_the_jobs_only_see_bars_that_are_confirmed_at_the_simulated_time(world: World) -> None:
    world.configure(cooldown=1)

    def last_stored_bar() -> str:
        with world.session() as session:
            stamp = session.scalar(
                select(func.max(OhlcvIntraday.bar_time)).where(OhlcvIntraday.code == world.code)
            )
        assert stamp is not None
        return stamp.strftime("%H:%M")

    world.tick("09:30")
    assert last_stored_bar() == "09:00"
    world.tick("10:00")
    assert last_stored_bar() == "09:30"
    world.tick("11:30")  # a tick skipped in between: the missing bars are fetched
    assert last_stored_bar() == "11:00"


def test_the_cooldown_blocks_repeats_within_it(world: World) -> None:
    world.configure(cooldown=3)

    results = [world.tick(hhmm) for hhmm in BAR_CLOSES]

    # bars 0, 3, 6, 9 and 12 alert; the 8 bars in between are in the cooldown
    assert [r.saved for r in results] == [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1]
    assert sum(r.suppressed for r in results) == 8
    starts = [a.bar_time for a in world.alerts("sell")]
    assert [s.strftime("%H:%M") for s in starts if s] == [
        "09:00",
        "10:30",
        "12:00",
        "13:30",
        "15:00",
    ]


def test_a_tick_that_fires_twice_does_not_alert_twice(world: World) -> None:
    world.configure(cooldown=6)

    first = world.tick("09:30")
    second = world.tick("09:30")

    assert (first.saved, second.saved, second.suppressed) == (1, 0, 1)
    assert len(world.alerts("sell")) == 1


def test_alerts_reach_telegram_as_summaries(world: World) -> None:
    world.configure(cooldown=1)

    world.tick("09:30")

    (request,) = world.telegram
    assert request["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert request["body"]["chat_id"] == "42"
    lines = request["body"]["text"].splitlines()
    assert lines[0].startswith("[매도 신호] 모의")
    assert lines[1] == "제안 수량: 33주"
    assert lines[2].startswith("현재가: ")
    assert lines[3].startswith("재매수 목표가: ")
    assert len(lines) == 4  # nothing but the summary
    (alert,) = world.alerts("sell")
    assert [d["status"] for d in alert.delivery] == ["stored", "sent"]


def test_a_switched_off_channel_sends_nothing_but_the_alert_is_still_kept(world: World) -> None:
    world.configure(cooldown=1)
    with world.session() as session:
        save_channels(session, {"telegram": False})
        session.commit()

    world.tick("09:30")

    assert world.telegram == []
    (alert,) = world.alerts("sell")
    assert alert.delivery == [{"channel": "in_app", "status": "stored"}]


def test_a_telegram_outage_loses_nothing(world: World) -> None:
    world.configure(cooldown=1)
    world.telegram_state["status"] = 500

    result = world.tick("09:30")

    assert result.saved == 1
    (alert,) = world.alerts("sell")
    assert alert.delivery[1]["status"] == "failed"
    assert alert.delivery[1]["error"] == "telegram rejected the message (HTTP 500)"
    assert TOKEN not in json.dumps(alert.delivery)


# --- cutting the feed --------------------------------------------------------------------------


def test_cutting_the_feed_stops_the_signals_and_raises_a_warning(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.configure(cooldown=2)
    first, second = world.tick("09:30"), world.tick("10:00")
    assert (first.saved, second.saved) == (1, 0)  # bar 09:30 is inside the 2-bar cooldown

    world.adapter.cut = True
    during = [world.tick("10:30"), world.tick("11:00")]

    for result in during:
        assert result.collected is False
        assert result.stale == ["intraday"]
    assert len(world.alerts("sell")) == 1  # no new signal while the data is stale
    (warning,) = world.alerts("data_stale")  # one warning; the second tick is in its cooldown
    assert "분봉 시세" in warning.evidence["message"]
    assert "ConnectionError" in warning.evidence["message"]
    assert "10:30" in warning.evidence["message"]
    assert warning.code is None and warning.holding_id is None
    assert "signals paused" in caplog.text
    assert any("[시세 갱신 지연 경고]" in r["body"]["text"] for r in world.telegram)


def test_the_health_endpoint_shows_the_warning_and_clears_it_on_recovery(world: World) -> None:
    world.configure(cooldown=2)
    world.tick("09:30")
    client = world.api()

    world.clock.now = at("2026-10-16 09:40")
    assert client.get("/api/health").json()["status"] == "ok"

    world.adapter.cut = True
    world.tick("10:30")
    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    (warning,) = health["warnings"]
    assert warning["source"] == "intraday"
    assert "분봉 시세" in warning["message"]
    assert health["collection"]["intraday"]["stale"] is True
    assert "ConnectionError" in health["collection"]["intraday"]["last_error"]

    world.adapter.cut = False
    world.tick("11:00")
    recovered = client.get("/api/health").json()
    assert recovered["status"] == "ok"
    assert recovered["warnings"] == []
    assert recovered["collection"]["intraday"]["last_error"] is None


def test_signals_resume_once_the_feed_is_back(world: World) -> None:
    world.configure(cooldown=2)
    world.tick("09:30")
    world.adapter.cut = True
    world.tick("10:30")
    world.tick("11:00")

    world.adapter.cut = False
    back = world.tick("11:30")

    assert back.collected and back.stale == []
    assert back.saved == 1
    starts = [a.bar_time.strftime("%H:%M") for a in world.alerts("sell") if a.bar_time]
    assert starts == ["09:00", "11:00"]  # the missed bars are not alerted late, the latest is


def test_errors_and_secrets_never_reach_the_health_response(world: World) -> None:
    world.configure(cooldown=2)
    client = world.api()
    world.adapter.cut = True
    world.tick("09:30")
    world.clock.now = at("2026-10-16 09:31")

    text = client.get("/api/health").text

    assert "ConnectionError" in text
    assert get_settings().app_password.get_secret_value() not in text  # masked as ***
    assert "***" in text
    assert TOKEN not in text


def test_a_failed_daily_collection_also_pauses_the_intraday_signals(world: World) -> None:
    world.configure(cooldown=1)
    world.adapter.cut = True
    failed = run_daily_job_at(world, "2026-10-16 18:00:10")
    world.adapter.cut = False

    monday = world.tick("09:30", day="2026-10-19")

    assert failed.collected is False and failed.stale == ["daily"]
    assert monday.stale == ["daily"]  # the intraday feed is fine, yesterday's close is not
    assert world.alerts("sell") == []


# --- the daily job ----------------------------------------------------------------------------


def run_daily_job_at(world: World, when: str) -> JobResult:
    world.clock.now = at(when)
    return run_daily_job(world.ctx)


def test_the_daily_job_raises_a_forced_sale_alert_before_the_next_open(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.configure(cooldown=6)
    monkeypatch.setattr(engine, "force_sell", force_sell_frame(index=True))

    result = run_daily_job_at(world, "2026-10-16 18:00:10")

    assert result.collected and result.stale == []
    (forced,) = world.alerts("force_sell")
    assert forced.suggested_quantity == 100
    assert forced.evidence == {"stock_ma_breakdown": False, "kospi_ma_breakdown": True}
    assert world.alerts("sell") == []  # intraday signals are the intraday job's
    assert any("[강제 매도 (5일선 이탈)]" in r["body"]["text"] for r in world.telegram)


def test_the_daily_alert_is_not_repeated_the_same_day(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.configure(cooldown=6)
    monkeypatch.setattr(engine, "force_sell", force_sell_frame(stock=True))

    run_daily_job_at(world, "2026-10-16 18:00:10")
    again = run_daily_job_at(world, "2026-10-16 18:30:10")

    assert again.saved == 0 and again.suppressed == 1
    assert len(world.alerts("force_sell")) == 1


def test_a_cycle_that_runs_out_gets_an_expiry_alert_in_the_daily_job(world: World) -> None:
    world.configure(cooldown=6)
    with world.session() as session:
        holdings_service.record_fill(
            session, world.holding_id, FillSide.SELL, 100_000, 30,  # type: ignore[arg-type]
            filled_at=at("2026-10-08 10:00"),
        )  # fmt: skip
        session.commit()

    run_daily_job_at(world, "2026-10-16 18:00:10")  # five trading days later, after the close

    (expired,) = world.alerts("expired")
    assert expired.evidence["choices"] == ["retry", "abandon"]
    with world.session() as session:
        holding = session.get(Holding, world.holding_id)
        assert holding is not None and holding.state.value == "expired"


def test_with_daily_signals_the_daily_job_evaluates_everything(world: World) -> None:
    world.configure(cooldown=6, length=BarLength.D1)

    intraday = world.tick("09:30")
    daily = run_daily_job_at(world, "2026-10-16 18:00:10")

    assert intraday.skipped is not None and "daily bars" in intraday.skipped
    assert daily.saved == 1
    (sell,) = world.alerts("sell")
    assert sell.evidence["bar_length"] == "1d"
    assert "latency_seconds" not in sell.evidence  # the 1-minute target is for minute bars


# --- when jobs do nothing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "hhmm", "reason"),
    [
        ("2026-10-17", "10:00", "not a trading day"),  # Saturday
        ("2026-10-09", "10:00", "not a trading day"),  # 한글날
        ("2026-10-16", "09:00", "outside market hours"),  # no bar has closed yet
        ("2026-10-16", "08:30", "outside market hours"),
        ("2026-10-16", "16:00", "outside market hours"),
    ],
)
def test_the_intraday_job_skips_holidays_and_hours_outside_the_session(
    world: World, day: str, hhmm: str, reason: str
) -> None:
    world.configure(cooldown=1)

    result = world.tick(hhmm, day)

    assert result.skipped == reason
    assert world.alerts() == []


def test_the_daily_job_skips_holidays_and_early_starts(world: World) -> None:
    assert run_daily_job_at(world, "2026-10-09 18:30:00").skipped == "not a trading day"
    assert run_daily_job_at(world, "2026-10-17 18:30:00").skipped == "not a trading day"
    assert run_daily_job_at(world, "2026-10-16 17:59:00").skipped == "before the scan time"


def test_without_holdings_the_job_still_records_a_successful_collection(world: World) -> None:
    world.configure(cooldown=1)
    with world.session() as session:
        holdings_service.remove(session, world.holding_id)
        session.commit()

    result = world.tick("09:30")

    assert result.collected and result.stale == [] and result.saved == 0
    client = world.api()
    world.clock.now = at("2026-10-16 09:31")
    assert client.get("/api/health").json()["collection"]["intraday"]["stale"] is False


def test_a_morning_without_a_closed_bar_yet_makes_no_alert_from_last_fridays_bar(
    world: World,
) -> None:
    world.configure(cooldown=1)
    run_daily_job_at(world, "2026-10-16 18:00:10")  # Friday's close is collected and fresh

    result = world.tick("09:30", day="2026-10-19")  # the mock market has no Monday bars

    assert result.collected is True and result.stale == []
    assert world.alerts("sell") == []  # Friday's last bar is 66 hours old, not "just closed"


def test_investor_flow_data_is_untouched_by_the_intraday_job(world: World) -> None:
    with world.session() as session:
        before = session.scalar(select(func.count()).select_from(InvestorFlowDaily))
    world.configure(cooldown=1)

    world.tick("09:30")

    with world.session() as session:
        assert session.scalar(select(func.count()).select_from(InvestorFlowDaily)) == before


def test_an_instrument_is_all_a_holding_needs_to_be_collected(world: World) -> None:
    from app.db.models import Instrument

    with world.session() as session:
        assert session.get(Instrument, world.code) is not None
        assert session.get(Instrument, world.code).market in {Market.KOSPI, Market.KOSDAQ}  # type: ignore[union-attr]
