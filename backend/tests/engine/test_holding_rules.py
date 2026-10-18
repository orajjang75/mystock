import pandas as pd

from app.engine.holding_rules import atr_stop_price, daily_downtrend, stop_breached
from tests.engine.helpers import flags, only_true_at, series


def test_a_falling_close_under_a_falling_average_is_a_downtrend() -> None:
    close = series(10, 10, 10, 9, 8, 7)  # 3-bar average: nan nan 10 9.67 9 8

    # bar 3: below the average but the slope (vs 2 bars ago) is not known yet; bars 4-5 qualify
    assert flags(daily_downtrend(close, ma_window=3, slope_bars=2)) == [
        False, False, False, False, True, True,
    ]  # fmt: skip


def test_the_close_must_be_strictly_below_the_average() -> None:
    assert not daily_downtrend(series(10, 10, 10, 10, 10), 3, 2).any()
    # the last close, 9, equals the 3-bar average of 8, 10 and 9: equal is not below
    assert not daily_downtrend(series(10, 10, 8, 10, 9), 3, 2).iloc[-1]


def test_a_close_under_a_rising_average_is_not_a_downtrend() -> None:
    close = series(1, 2, 3, 10, 4)  # average 2 -> 5 -> 5.67 while the close dips to 4

    result = daily_downtrend(close, 3, 2)

    assert not result.iloc[-1]


def test_a_flat_average_is_not_falling() -> None:
    close = series(10, 10, 9, 11, 9.5)  # averages 9.67, 10, 9.83: no net fall over 2 bars

    assert not daily_downtrend(close, 3, 2).iloc[-1]


def test_the_default_is_sixty_days_and_five_bars() -> None:
    falling = series(*[100.0 - i for i in range(70)])

    result = daily_downtrend(falling)

    assert not result.iloc[:64].any()  # needs 60 bars plus 5 for the slope
    assert result.iloc[64:].all()


def test_the_trend_filter_works_on_many_stocks_at_once() -> None:
    wide = pd.DataFrame({"down": [10.0, 10, 10, 9, 8, 7], "flat": [10.0] * 6})

    result = daily_downtrend(wide, 3, 2)

    assert result.iloc[-1].to_dict() == {"down": True, "flat": False}


def test_the_stop_is_the_average_cost_minus_two_atr() -> None:
    assert atr_stop_price(100.0, series(5), 2.0).iloc[0] == 90.0
    assert atr_stop_price(100.0, series(5)).iloc[0] == 90.0  # the default multiple is 2


def test_a_price_at_the_stop_is_not_a_breach() -> None:
    stop = series(90, 90, 90)

    assert only_true_at(stop_breached(series(89.99, 90, 95), stop), 0)
