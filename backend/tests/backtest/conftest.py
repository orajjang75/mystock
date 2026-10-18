"""A small mock market with history for the backtest tests.

30 KOSPI + 10 KOSDAQ stocks, 500 sessions of daily bars, 60 sessions of 30-minute bars, monthly
universe snapshots over the last year, and two stocks that were delisted along the way.
Ingested once per test session.
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.mock import MockAdapter, Scenario
from app.backtest.dataset import backfill_snapshots
from app.core.market import KST
from app.jobs.ingest import run_ingest
from app.services.universe import UniverseSpec
from tests.conftest import END_DATE, sqlite_engine

SPEC = UniverseSpec(kospi_top=20, kosdaq_top=5, min_avg_trading_value=1_000_000_000)
AFTER_CLOSE = datetime(2026, 10, 16, 16, 0, tzinfo=KST)
BACKFILL_FROM = date(2025, 10, 1)


def pick_delisted(adapter: MockAdapter) -> dict[str, int]:
    """Two ordinary KOSPI stocks (not flagged, mid-ranked) that stop trading 40 and 90 sessions
    before the end."""
    ordinary = [
        s
        for s in adapter.stocks
        if s.market.value == "KOSPI"
        and not (s.is_preferred or s.is_admin_issue or s.is_halted or s.is_warning or s.is_illiquid)
        and 5 <= s.position <= 14
    ]
    chosen = [s for s in ordinary if s.scenario is not Scenario.UPTREND][:2]
    return {chosen[0].code: 40, chosen[1].code: 90}


@pytest.fixture(scope="session")
def bt_adapter() -> MockAdapter:
    plain = MockAdapter(seed=42, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    return MockAdapter(
        seed=42, end_date=END_DATE, n_kospi=30, n_kosdaq=10, delistings=pick_delisted(plain)
    )


@pytest.fixture(scope="session")
def bt_engine(bt_adapter: MockAdapter) -> Engine:
    engine = sqlite_engine()
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        backfill_snapshots(
            session, bt_adapter, BACKFILL_FROM, END_DATE - timedelta(days=1), spec=SPEC
        )
        run_ingest(session, bt_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SPEC)
    return engine


@pytest.fixture
def bt_session(bt_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=bt_engine, expire_on_commit=False)() as session:
        yield session
