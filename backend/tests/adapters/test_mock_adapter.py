from datetime import date

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app.adapters.base import DAILY_COLUMNS, FLOW_COLUMNS, INDEX_COLUMNS, INTRADAY_COLUMNS
from app.adapters.mock import BARS_PER_DAY, MockAdapter, Scenario
from app.core.market import KST
from app.db.enums import Market
from tests.conftest import END_DATE

FIRST = date(2020, 1, 1)


def daily(adapter: MockAdapter, code: str) -> pd.DataFrame:
    return adapter.fetch_daily_ohlcv(code, FIRST, END_DATE)


def codes_of(adapter: MockAdapter, scenario: Scenario) -> list[str]:
    return [s.code for s in adapter.stocks if s.scenario is scenario]


def test_listings_cover_kospi_120_and_kosdaq_30(mock_adapter: MockAdapter) -> None:
    listings = mock_adapter.fetch_listings(END_DATE)

    assert sum(item.market is Market.KOSPI for item in listings) == 120
    assert sum(item.market is Market.KOSDAQ for item in listings) == 30
    assert len({item.code for item in listings}) == 150


def test_listings_limit_returns_the_largest_per_market(mock_adapter: MockAdapter) -> None:
    everything = mock_adapter.fetch_listings(END_DATE)
    limited = mock_adapter.fetch_listings(END_DATE, limit_per_market=10)

    for market in Market:
        expected = sorted(
            (item for item in everything if item.market is market),
            key=lambda item: -item.market_cap,
        )[:10]
        assert [item.code for item in limited if item.market is market] == [
            item.code for item in expected
        ]


def test_same_seed_gives_identical_data_and_other_seed_differs(mock_adapter: MockAdapter) -> None:
    again = MockAdapter(seed=42, end_date=END_DATE)
    other = MockAdapter(seed=43, end_date=END_DATE)
    code = mock_adapter.stocks[0].code

    assert_frame_equal(daily(mock_adapter, code), daily(again, code))
    assert_frame_equal(
        mock_adapter.fetch_investor_flow(code, FIRST, END_DATE),
        again.fetch_investor_flow(code, FIRST, END_DATE),
    )
    assert_frame_equal(
        mock_adapter.fetch_intraday_30m(code, FIRST, END_DATE),
        again.fetch_intraday_30m(code, FIRST, END_DATE),
    )
    assert not daily(mock_adapter, code)["close"].equals(daily(other, code)["close"])


def test_daily_bars_are_500_weekdays_ending_at_end_date(mock_adapter: MockAdapter) -> None:
    frame = daily(mock_adapter, mock_adapter.stocks[0].code)

    assert list(frame.columns) == DAILY_COLUMNS
    assert len(frame) == 500
    assert frame.index.name == "trade_date"
    assert frame.index[-1] == pd.Timestamp(END_DATE)
    assert (pd.DatetimeIndex(frame.index).dayofweek < 5).all()
    assert frame.index.is_monotonic_increasing


def test_daily_prices_are_consistent(mock_adapter: MockAdapter) -> None:
    for stock in mock_adapter.stocks:
        frame = daily(mock_adapter, stock.code)
        assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all(), stock.code
        assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all(), stock.code
        assert (frame["low"] > 0).all(), stock.code
        assert (frame["volume"] > 0).all(), stock.code
        assert (frame["trading_value"] == frame["volume"] * frame["close"]).all(), stock.code


def test_fetch_ranges_are_inclusive(mock_adapter: MockAdapter) -> None:
    code = mock_adapter.stocks[0].code
    frame = mock_adapter.fetch_daily_ohlcv(code, date(2026, 10, 12), date(2026, 10, 14))

    assert [ts.date() for ts in frame.index] == [
        date(2026, 10, 12),
        date(2026, 10, 13),
        date(2026, 10, 14),
    ]


def test_intraday_has_60_days_of_13_bars_in_kst(mock_adapter: MockAdapter) -> None:
    frame = mock_adapter.fetch_intraday_30m(mock_adapter.stocks[0].code, FIRST, END_DATE)

    assert list(frame.columns) == INTRADAY_COLUMNS
    assert len(frame) == 60 * BARS_PER_DAY
    assert str(pd.DatetimeIndex(frame.index).tz) == str(KST)
    times = pd.DatetimeIndex(frame.index).strftime("%H:%M")
    assert times.min() == "09:00"
    assert times.max() == "15:00"
    assert frame.groupby(pd.DatetimeIndex(frame.index).date).size().eq(BARS_PER_DAY).all()


def test_intraday_bars_add_up_to_the_daily_bar(mock_adapter: MockAdapter) -> None:
    stock = mock_adapter.stocks[5]
    bars = mock_adapter.fetch_intraday_30m(stock.code, FIRST, END_DATE)
    days = daily(mock_adapter, stock.code).iloc[-60:]

    by_day = bars.groupby(pd.DatetimeIndex(bars.index).date)
    assert (by_day["open"].first().to_numpy() == days["open"].to_numpy()).all()
    assert (by_day["close"].last().to_numpy() == days["close"].to_numpy()).all()
    assert (by_day["high"].max().to_numpy() == days["high"].to_numpy()).all()
    assert (by_day["low"].min().to_numpy() == days["low"].to_numpy()).all()
    assert (by_day["volume"].sum().to_numpy() == days["volume"].to_numpy()).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1)).all()
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1)).all()


def test_investor_flow_shape(mock_adapter: MockAdapter) -> None:
    code = mock_adapter.stocks[0].code
    flow = mock_adapter.fetch_investor_flow(code, FIRST, END_DATE)

    assert list(flow.columns) == FLOW_COLUMNS
    assert flow.index.equals(daily(mock_adapter, code).index)
    assert (flow.dtypes == "int64").all()


def test_index_daily_is_a_kospi_series(mock_adapter: MockAdapter) -> None:
    frame = mock_adapter.fetch_index_daily("KOSPI", FIRST, END_DATE)

    assert list(frame.columns) == INDEX_COLUMNS
    assert len(frame) == 500
    assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
    with pytest.raises(KeyError):
        mock_adapter.fetch_index_daily("KOSDAQ", FIRST, END_DATE)


def test_unknown_code_is_an_error(mock_adapter: MockAdapter) -> None:
    with pytest.raises(KeyError):
        mock_adapter.fetch_daily_ohlcv("NOPE", FIRST, END_DATE)


def test_all_four_scenarios_are_present(mock_adapter: MockAdapter) -> None:
    for scenario in Scenario:
        assert len(codes_of(mock_adapter, scenario)) >= 20, scenario


def test_rebound_stocks_bottom_then_bounce_with_volume_and_buying(
    mock_adapter: MockAdapter,
) -> None:
    for code in codes_of(mock_adapter, Scenario.REBOUND):
        frame = daily(mock_adapter, code)
        close = frame["close"]
        assert 100 * (close.iloc[-1] / close.iloc[-252:].max() - 1) <= -30, code
        assert close.iloc[-1] > close.iloc[-10:].min() * 1.05, code  # bounced off the low
        last3 = frame.iloc[-3:]
        assert (last3["close"] > last3["open"]).all(), code  # bullish candles
        assert frame["volume"].iloc[-1] >= 2 * frame["volume"].iloc[-21:-1].mean(), code
        flow = mock_adapter.fetch_investor_flow(code, FIRST, END_DATE)
        net = flow.sum(axis=1)
        assert (flow.iloc[-5:] > 0).all().all(), code
        assert net.iloc[-5:].sum() > 0 >= net.iloc[-10:-5].sum(), code  # 순매수 전환


@pytest.mark.parametrize("scenario", [Scenario.DOWNTREND, Scenario.SIDEWAYS, Scenario.UPTREND])
def test_other_scenarios_do_not_reach_the_drawdown_gate(
    mock_adapter: MockAdapter, scenario: Scenario
) -> None:
    for code in codes_of(mock_adapter, scenario):
        close = daily(mock_adapter, code)["close"]
        assert 100 * (close.iloc[-1] / close.iloc[-252:].max() - 1) > -30, code


def test_downtrend_stocks_keep_falling(mock_adapter: MockAdapter) -> None:
    for code in codes_of(mock_adapter, Scenario.DOWNTREND):
        close = daily(mock_adapter, code)["close"]
        assert close.iloc[-1] < close.iloc[-120] < close.iloc[-250], code
