"""The mock market, its clock and the jobs, as the browser tests drive them."""

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import time_machine
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adapters.mock import MockAdapter, Scenario
from app.core.config import get_settings
from app.core.market import KST
from app.db.base import Base
from app.db.enums import BarLength
from app.db.models import Instrument
from app.db.session import get_engine, get_sessionmaker
from app.engine.holding_rules import daily_downtrend
from app.jobs.monitor import JobContext, run_daily_job, run_intraday_job
from app.services import holdings as holdings_service
from app.services.alert_engine import load_daily_context
from app.services.settings import (
    save_alert_cooldown_bars,
    save_refresh_seconds,
    save_signal_bar_length,
)
from app.services.universe import UniverseSpec, load_universe
from e2e import signals

logger = logging.getLogger(__name__)

END_DATE = date(2026, 10, 23)  # the mock market has bars through this Friday
EVENING_BEFORE = datetime(2026, 10, 15, 18, 0, 10, tzinfo=KST)
SELL_BAR_CLOSE = datetime(2026, 10, 16, 11, 0, 10, tzinfo=KST)
DIP_FROM = pd.Timestamp("2026-10-16 12:00", tz=KST)
DIP_FACTOR = 0.95  # the stock trades 5 % lower from noon, so a rebuy can be cheaper than the sale
HOLDING_QUANTITY = 300  # a third is 100 shares: a 5 % dip buys several back
SPEC = UniverseSpec(kospi_top=20, kosdaq_top=5)


class ScriptedAdapter(MockAdapter):
    """The mock market, except that one stock drops 5 % at noon on Friday 2026-10-16."""

    dip_code: str | None = None

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> Any:
        frame = super().fetch_intraday_30m(code, start, end)
        if code == self.dip_code:
            noon = (frame.index >= DIP_FROM) & (frame.index < DIP_FROM + pd.Timedelta(days=1))
            for column in ("open", "high", "low", "close"):
                frame.loc[noon, column] = (frame.loc[noon, column] * DIP_FACTOR).round()
        return frame


class Clock:
    """The process-wide mock time: ``datetime.now`` and ``time.time`` follow it (time-machine)."""

    def __init__(self) -> None:
        self._coordinates: Any = None

    def set(self, now: datetime) -> None:
        if self._coordinates is None:
            self._coordinates = time_machine.travel(now, tick=True).start()
        else:
            self._coordinates.move_to(now, tick=True)

    @property
    def now(self) -> datetime:
        return datetime.now(KST)


@dataclass(frozen=True)
class Scenario_:
    holding_id: int
    code: str
    name: str


class World:
    def __init__(self) -> None:
        self.clock = Clock()
        self.adapter = ScriptedAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
        self.ctx = JobContext(get_sessionmaker(), self.adapter, get_settings(), spec=SPEC)
        signals.install()

    def reset(self) -> Scenario_:
        """Empty the database and rebuild the evening before 2026-10-16 with one holding."""
        engine = get_engine()
        tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        signals.reset()
        self.adapter.dip_code = None
        self.clock.set(EVENING_BEFORE)
        result = run_daily_job(self.ctx)
        if result.skipped or not result.collected:
            raise RuntimeError(f"the setup scan did not run: {result}")

        with get_sessionmaker()() as session:
            code = self._steady_stock(session)
            daily = load_daily_context(session, code, SELL_BAR_CLOSE).bars
            avg_price = round(float(daily["close"].iloc[-1]) * 0.9)
            holding = holdings_service.register(session, code, HOLDING_QUANTITY, avg_price)  # type: ignore[arg-type]
            save_alert_cooldown_bars(session, 1)  # nothing is held back but the same bar twice
            save_signal_bar_length(session, BarLength.M60)
            save_refresh_seconds(session, 10)
            name = session.get(Instrument, code)
            session.commit()
            holding_id = holding.id
        self.adapter.dip_code = code
        return Scenario_(holding_id, code, name.name if name else code)

    def _steady_stock(self, session: Session) -> str:
        """An uptrend stock whose daily trend is not down, so that the sell alert is allowed."""
        for member in load_universe(session):
            if self.adapter.stock(member.code).scenario is not Scenario.UPTREND:
                continue
            closes = load_daily_context(session, member.code, SELL_BAR_CLOSE).bars["close"]
            if not daily_downtrend(closes).iloc[-1]:
                return member.code
        raise RuntimeError("the mock market has no steady uptrend stock")

    def tick(self, job: str) -> dict[str, Any]:
        result = run_intraday_job(self.ctx) if job == "intraday" else run_daily_job(self.ctx)
        return asdict(result)

    def known_codes(self, session: Session) -> list[str]:
        return list(session.scalars(select(Instrument.code)))
