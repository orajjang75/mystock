from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.mock import BARS_PER_DAY, MockAdapter
from app.core.market import KST
from app.db.enums import BarLength
from app.db.models import (
    Holding,
    IndexDaily,
    Instrument,
    InvestorFlowDaily,
    OhlcvDaily,
    OhlcvIntraday,
)
from app.jobs.ingest import run_ingest
from app.services.bars import load_intraday
from app.services.universe import UniverseSpec
from tests.conftest import END_DATE

AFTER_CLOSE = datetime(2026, 10, 16, 16, 0, tzinfo=KST)
SMALL = UniverseSpec(kospi_top=20, kosdaq_top=5)


@pytest.fixture(scope="module")
def small_adapter() -> MockAdapter:
    return MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_ingest_fills_daily_intraday_flow_and_index(
    session: Session, small_adapter: MockAdapter
) -> None:
    summary = run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)

    assert summary.universe == 25
    assert summary.daily == count(session, OhlcvDaily) == 25 * 500
    assert summary.investor_flow == count(session, InvestorFlowDaily) == 25 * 500
    assert summary.intraday == count(session, OhlcvIntraday) == 25 * 60 * BARS_PER_DAY
    assert summary.index_daily == count(session, IndexDaily) == 500
    ranked = session.scalar(select(func.count()).where(Instrument.market_cap_rank.is_not(None)))
    assert ranked == 25


def test_running_ingest_twice_does_not_duplicate_rows(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)
    first = (count(session, OhlcvDaily), count(session, OhlcvIntraday))

    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)

    assert (count(session, OhlcvDaily), count(session, OhlcvIntraday)) == first


def test_unconfirmed_bars_are_not_stored(session: Session, small_adapter: MockAdapter) -> None:
    # 10:45 on the last day: today's daily bar is not final, and neither is the 10:30 bar.
    now = datetime(2026, 10, 16, 10, 45, tzinfo=KST)

    run_ingest(session, small_adapter, as_of=END_DATE, now=now, spec=SMALL)

    assert session.scalar(select(func.max(OhlcvDaily.trade_date))) == date(2026, 10, 15)
    assert session.scalar(select(func.max(InvestorFlowDaily.trade_date))) == date(2026, 10, 15)
    assert session.scalar(select(func.max(IndexDaily.trade_date))) == date(2026, 10, 15)
    last_bar = session.scalar(select(func.max(OhlcvIntraday.bar_time)))
    assert last_bar is not None
    stamp = pd.Timestamp(last_bar)  # SQLite returns naive KST wall time, PostgreSQL aware
    stamp = stamp.tz_localize(KST) if stamp.tzinfo is None else stamp.tz_convert(KST)
    assert stamp == pd.Timestamp("2026-10-16 10:00", tz=KST)


def test_the_day_is_stored_once_the_session_has_closed(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(
        session,
        small_adapter,
        as_of=END_DATE,
        now=datetime(2026, 10, 16, 15, 30, tzinfo=KST),
        spec=SMALL,
    )

    assert session.scalar(select(func.max(OhlcvDaily.trade_date))) == END_DATE


def test_stored_30m_bars_round_trip_with_their_kst_times(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)
    code = session.scalars(
        select(Instrument.code).where(Instrument.market_cap_rank == 1, Instrument.market == "KOSPI")
    ).one()

    stored = load_intraday(session, code, BarLength.M30, date(2020, 1, 1), END_DATE)
    original = small_adapter.fetch_intraday_30m(code, date(2020, 1, 1), END_DATE)

    assert len(stored) == len(original) == 60 * BARS_PER_DAY
    assert (stored.index == original.index).all()
    assert str(pd.DatetimeIndex(stored.index).tz) == str(KST)
    assert (stored["close"].to_numpy() == original["close"].to_numpy()).all()
    assert (stored["volume"].to_numpy() == original["volume"].to_numpy()).all()


def test_60m_bars_come_from_the_stored_30m_bars_and_the_last_one_is_30_minutes(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)
    code = session.scalars(select(Instrument.code).where(Instrument.market_cap_rank == 2)).first()
    assert code is not None

    hourly = load_intraday(session, code, BarLength.M60, date(2020, 1, 1), END_DATE)

    assert len(hourly) == 60 * 7
    last_of_each_day = hourly.groupby(pd.DatetimeIndex(hourly.index).date).tail(1)
    assert (pd.DatetimeIndex(last_of_each_day.index).strftime("%H:%M") == "15:00").all()
    assert (last_of_each_day["span_minutes"] == 30).all()
    others = hourly.drop(last_of_each_day.index)
    assert (others["span_minutes"] == 60).all()
    assert hourly["is_complete"].all()
    assert (
        session.scalar(select(func.count()).where(OhlcvIntraday.bar_length == BarLength.M60)) == 0
    )


def test_daily_bars_are_not_an_intraday_length(session: Session) -> None:
    with pytest.raises(ValueError, match="not intraday"):
        load_intraday(session, "900010", BarLength.D1, END_DATE, END_DATE)


def test_full_size_ingest_for_kospi_100_and_kosdaq_20(
    engine: Engine, mock_adapter: MockAdapter
) -> None:
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        summary = run_ingest(session, mock_adapter, as_of=END_DATE, now=AFTER_CLOSE)

        assert summary.universe == 120
        assert summary.daily == 120 * 500
        assert summary.investor_flow == 120 * 500
        assert summary.intraday == 120 * 60 * BARS_PER_DAY
        assert summary.index_daily == 500
        assert count(session, OhlcvDaily) == summary.daily
        assert count(session, OhlcvIntraday) == summary.intraday
        kospi = select(func.count()).where(
            Instrument.market_cap_rank.is_not(None), Instrument.market == "KOSPI"
        )
        assert session.scalar(kospi) == 100


def test_quotes_make_health_report_a_last_update(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)

    updated = session.scalar(select(func.max(OhlcvDaily.updated_at)))

    assert updated is not None
    assert datetime.now(KST) - pd.Timestamp(updated).tz_localize(None).tz_localize(KST) < timedelta(
        days=2
    )


def test_stocks_held_outside_the_universe_are_collected_too(
    session: Session, small_adapter: MockAdapter
) -> None:
    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)
    outside = next(s.code for s in small_adapter.stocks if s.is_admin_issue)
    assert session.scalar(select(func.count()).where(OhlcvDaily.code == outside)) == 0
    session.add(Holding(code=outside, quantity=10, avg_price=1, start_quantity=10))
    session.commit()

    run_ingest(session, small_adapter, as_of=END_DATE, now=AFTER_CLOSE, spec=SMALL)

    assert session.scalar(select(func.count()).where(OhlcvDaily.code == outside)) == 500
    assert (session.scalar(select(func.count()).where(OhlcvIntraday.code == outside)) or 0) > 0
    assert session.scalar(select(func.count()).where(InvestorFlowDaily.code == outside)) == 500
