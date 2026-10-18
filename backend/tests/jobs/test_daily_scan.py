import logging
from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.mock import MockAdapter
from app.core.config import get_settings
from app.core.market import KST, is_trading_day
from app.db.models import OhlcvDaily
from app.jobs.daily_scan import run_daily_scan
from app.services.screener import results_for
from app.services.universe import UniverseSpec
from tests.conftest import END_DATE, sqlite_engine

SMALL = UniverseSpec(kospi_top=20, kosdaq_top=5)


class UntouchedAdapter(MockAdapter):
    """Fails the test if the job asks it for any data."""

    def fetch_listings(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the job must not touch the adapter")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


# --- calendar ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 16), True),  # an ordinary Friday
        (date(2026, 10, 17), False),  # Saturday
        (date(2026, 10, 18), False),  # Sunday
        (date(2026, 10, 9), False),  # 한글날
        (date(2026, 9, 25), False),  # 추석
        (date(2026, 5, 1), False),  # 노동절
        (date(2026, 12, 31), False),  # KRX year-end closing
        (date(2026, 12, 30), True),
    ],
)
def test_trading_days(day: date, expected: bool) -> None:
    assert is_trading_day(day) is expected


# --- job --------------------------------------------------------------------------------------


def test_the_scan_time_is_a_setting() -> None:
    assert get_settings().daily_scan_time.strftime("%H:%M") == "18:00"


def test_a_holiday_is_skipped_without_touching_the_data_source() -> None:
    with sessionmaker(bind=sqlite_engine())() as db:
        result = run_daily_scan(db, UntouchedAdapter(), now=at("2026-10-09 19:00"))

    assert result.skipped == "not a trading day"
    assert result.scan is None


def test_a_weekend_is_skipped() -> None:
    with sessionmaker(bind=sqlite_engine())() as db:
        result = run_daily_scan(db, UntouchedAdapter(), now=at("2026-10-17 19:00"))

    assert result.skipped == "not a trading day"


def test_nothing_runs_before_the_investor_flow_data_is_final() -> None:
    with sessionmaker(bind=sqlite_engine())() as db:
        result = run_daily_scan(db, UntouchedAdapter(), now=at("2026-10-16 17:59"))

    assert result.skipped == "before the scan time"


def test_after_the_scan_time_it_ingests_scans_and_logs_the_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    engine = sqlite_engine()

    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        result = run_daily_scan(db, adapter, now=at("2026-10-16 18:00"), spec=SMALL)
        saved = results_for(db, END_DATE)

    assert result.skipped is None
    assert result.scan_date == END_DATE
    assert result.ingest is not None and result.ingest.universe == 25
    assert result.scan is not None and result.scan.saved == len(saved) > 0
    assert 0 <= result.elapsed_seconds < 600
    assert "daily scan finished in" in caplog.text
    assert "target 600s" in caplog.text


def test_the_run_is_committed(caplog: pytest.LogCaptureFixture) -> None:
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    engine = sqlite_engine()
    with sessionmaker(bind=engine)() as db:
        run_daily_scan(db, adapter, now=at("2026-10-16 18:30"), spec=SMALL)

    with sessionmaker(bind=engine)() as fresh:
        assert (fresh.scalar(select(func.count()).select_from(OhlcvDaily)) or 0) > 0
        assert results_for(fresh, END_DATE)


def test_an_explicit_date_skips_the_scan_time_check_but_not_holidays() -> None:
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    with sessionmaker(bind=sqlite_engine(), expire_on_commit=False)() as db:
        # 16:00 is before the 18:00 scan time, yet an explicitly requested day still runs
        ran = run_daily_scan(
            db, adapter, now=at("2026-10-16 16:00"), scan_date=END_DATE, spec=SMALL
        )
        holiday = run_daily_scan(db, UntouchedAdapter(), scan_date=date(2026, 10, 9))

    assert ran.skipped is None
    assert holiday.skipped == "not a trading day"


def test_a_day_whose_session_has_not_closed_has_no_confirmed_bars_to_scan() -> None:
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    with sessionmaker(bind=sqlite_engine())() as db:
        result = run_daily_scan(
            db, adapter, now=at("2026-10-16 10:00"), scan_date=END_DATE, spec=SMALL
        )

    assert result.skipped is not None and "No daily bars for 2026-10-16" in result.skipped


def test_force_runs_even_on_a_non_trading_day_but_still_needs_bars() -> None:
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    with sessionmaker(bind=sqlite_engine())() as db:
        result = run_daily_scan(db, adapter, now=at("2026-10-17 19:00"), force=True, spec=SMALL)

    assert result.skipped is not None and "No daily bars for 2026-10-17" in result.skipped
    assert result.ingest is not None  # data was collected, the scan itself had nothing to read
