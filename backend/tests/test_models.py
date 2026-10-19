from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.enums import BarLength, Market
from app.db.models import Instrument, InvestorFlowDaily, OhlcvDaily, OhlcvIntraday, ScanResult

# PRD 8장 테이블 표.
PRD_TABLES = {
    "instruments",
    "ohlcv_daily",
    "index_daily",
    "investor_flow_daily",
    "ohlcv_intraday",
    "scan_results",
    "watchlist",
    "holdings",
    "cycles",
    "alerts",
    "settings",
    "fills",
    "backtest_runs",
}
# Not a PRD 8장 table: PRD 10장 asks for the universe as ranked at each past date, so the daily
# scan (and a backfill) store who was in it, with their rank and market cap. job_runs is the log of
# every scheduled run that the 모의 운영 report (PRD 로드맵 5단계) is built from.
ADDED_TABLES = {"universe_snapshots", "job_runs"}

PRICES = {
    "open": Decimal("100"),
    "high": Decimal("110"),
    "low": Decimal("95"),
    "close": Decimal("105"),
}


def test_all_prd_tables_exist(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) == PRD_TABLES | ADDED_TABLES
    assert set(Base.metadata.tables) == PRD_TABLES | ADDED_TABLES


@pytest.fixture
def stock(db: Session) -> Instrument:
    instrument = Instrument(code="005930", name="삼성전자", market=Market.KOSPI)
    db.add(instrument)
    db.commit()
    return instrument


def test_instrument_flags_default_to_false(db: Session, stock: Instrument) -> None:
    db.refresh(stock)

    assert (stock.is_admin_issue, stock.is_halted, stock.is_warning) == (False, False, False)


def test_daily_bar_is_unique_per_code_and_date(db: Session, stock: Instrument) -> None:
    bar = {"code": stock.code, "trade_date": date(2026, 10, 16), "volume": 1, "trading_value": 1}
    db.add(OhlcvDaily(**bar, **PRICES))
    db.commit()

    db.add(OhlcvDaily(**bar, **PRICES))
    with pytest.raises(IntegrityError):
        db.commit()


def test_investor_flow_is_unique_per_code_and_date(db: Session, stock: Instrument) -> None:
    row = {
        "code": stock.code,
        "trade_date": date(2026, 10, 16),
        "foreign_net_buy": 1,
        "institution_net_buy": -1,
    }
    db.add(InvestorFlowDaily(**row))
    db.commit()

    db.add(InvestorFlowDaily(**row))
    with pytest.raises(IntegrityError):
        db.commit()


def test_intraday_bar_is_unique_per_code_length_and_time(db: Session, stock: Instrument) -> None:
    bar = {
        "code": stock.code,
        "bar_length": BarLength.M30,
        "bar_time": datetime(2026, 10, 16, 9, 30, tzinfo=UTC),
        "volume": 1,
    }
    db.add(OhlcvIntraday(**bar, **PRICES))
    db.commit()

    # Same time, different bar length is a different row.
    db.add(OhlcvIntraday(**{**bar, "bar_length": BarLength.M60}, **PRICES))
    db.commit()

    db.add(OhlcvIntraday(**bar, **PRICES))
    with pytest.raises(IntegrityError):
        db.commit()


def test_scan_result_is_unique_per_date_and_code(db: Session, stock: Instrument) -> None:
    row = {"scan_date": date(2026, 10, 16), "code": stock.code, "score": Decimal("72.5")}
    db.add(ScanResult(**row, tags=["rsi_cross"], indicators={"rsi": 31.2}, params={"rsi": 14}))
    db.commit()

    db.add(ScanResult(**row))
    with pytest.raises(IntegrityError):
        db.commit()


def test_time_series_rows_require_a_known_instrument(db: Session) -> None:
    db.add(
        OhlcvDaily(
            code="UNKNOWN", trade_date=date(2026, 10, 16), volume=1, trading_value=1, **PRICES
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
