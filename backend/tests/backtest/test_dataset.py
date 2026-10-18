from datetime import date

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.adapters.mock import MockAdapter
from app.backtest.config import UniverseOptions
from app.backtest.dataset import BacktestDataError, load_dataset, suspected_unadjusted
from app.db.enums import BarLength
from tests.backtest.conftest import pick_delisted
from tests.conftest import END_DATE


def test_the_dataset_reads_the_stored_bars_of_everyone_who_was_ever_a_member(
    bt_session: Session,
) -> None:
    data = load_dataset(bt_session, UniverseOptions())

    assert data.eval_end == pd.Timestamp(END_DATE)
    assert {"open", "close", "volume", "trading_value", "foreign_net_buy"} <= set(data.panel)
    assert len(data.codes) > 25  # the members of twelve monthly snapshots, not only today's
    assert data.notes["adjusted_prices"] is True
    assert data.notes["snapshots"] >= 12
    assert data.index["close"].notna().all()
    assert data.eval_start > data.dates[0]  # the indicator warm-up comes first


def test_the_universe_of_a_day_is_the_ranking_stored_for_that_day(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions(point_in_time=True))

    early = data.members.loc["2025-11-14"].sum()
    late = data.members.loc[END_DATE.isoformat()].sum()

    assert 0 < early <= 25
    assert 0 < late <= 25
    # the members change over time (ranks move, delisted ones drop out)
    assert not data.members.loc["2025-11-14"].equals(
        data.members.loc[END_DATE.isoformat()]  # type: ignore[arg-type]
    )


def test_a_fixed_universe_uses_the_latest_ranking_for_every_day(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions(point_in_time=False))

    rows = data.members.loc["2025-11-14" : END_DATE.isoformat()]
    assert (rows == rows.iloc[0]).all().all() or rows.eq(rows.iloc[0], axis=1).all().all()
    assert "고정" in data.notes["universe"]


def test_delisted_stocks_are_kept_by_default_and_stop_being_members_after_their_last_bar(
    bt_session: Session, bt_adapter: MockAdapter
) -> None:
    delisted = pick_delisted(bt_adapter)

    data = load_dataset(bt_session, UniverseOptions(include_delisted=True))

    assert set(delisted) <= data.delisted
    for code in delisted:
        last = data.last_bar[code]
        assert last < data.eval_end
        assert not data.members.loc[data.members.index > last, code].any()
        assert data.members.loc[:last, code].any()  # it was a member before that
        assert data.notes["delisted"].count(code) == 1


def test_survivors_only_drops_them_from_the_whole_period(
    bt_session: Session, bt_adapter: MockAdapter
) -> None:
    delisted = pick_delisted(bt_adapter)

    data = load_dataset(bt_session, UniverseOptions(include_delisted=False))

    assert not set(delisted) & set(data.codes)
    assert set(delisted) <= set(data.notes["delisted"])  # still reported as dropped
    assert not data.delisted & set(data.codes)


def test_the_last_prices_of_a_delisted_stock_show_its_slide(
    bt_session: Session, bt_adapter: MockAdapter
) -> None:
    code = next(iter(pick_delisted(bt_adapter)))
    data = load_dataset(bt_session, UniverseOptions())

    closes = data.daily_bars(code)["close"]

    assert closes.iloc[-1] <= 0.7 * closes.iloc[-11]  # the ten-bar slide to 60 %


def test_the_mock_series_are_adjusted(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions())

    assert "suspected_unadjusted" not in data.notes


def test_a_split_left_in_the_prices_is_reported() -> None:
    close = pd.DataFrame(
        {"A": [100.0, 101.0, 50.5, 51.0], "B": [10.0, 10.1, 10.2, 10.1]},
        index=pd.bdate_range("2026-01-05", periods=4),
    )

    assert suspected_unadjusted(close) == {"A": 1}


def test_intraday_bars_come_from_the_stored_30_minute_bars(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions())
    code = next(c for c in data.codes if c not in data.delisted)

    half = data.bars(code, BarLength.M30)
    hour = data.bars(code, BarLength.M60)
    daily = data.bars(code, BarLength.D1)

    assert len(half) > len(hour) > 0
    assert half.index[0].hour == 9
    assert pd.DatetimeIndex(hour.index).tz is not None
    assert set(daily.columns) >= {"open", "close", "volume"}
    assert data.intraday_span() is not None


def test_an_empty_database_is_an_error_not_a_crash() -> None:
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import sqlite_engine

    with sessionmaker(bind=sqlite_engine())() as empty, pytest.raises(BacktestDataError):
        load_dataset(empty, UniverseOptions(), end=date(2026, 10, 16))
