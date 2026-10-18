import pandas as pd

from app.engine.force_sell import force_sell, ma_breakdown, ma_recovered
from tests.engine.helpers import flags, only_true_at, series


def test_breakdown_fires_only_on_the_first_bar_the_short_average_drops_below() -> None:
    close = series(5, 5, 5, 4, 3)  # 2-bar vs 3-bar averages

    # ma2: nan 5 5 4.5 3.5   ma3: nan nan 5 4.667 4
    assert only_true_at(ma_breakdown(close, 2, 3), 3)


def test_an_equal_previous_bar_still_counts_and_equality_now_does_not() -> None:
    assert only_true_at(ma_breakdown(series(5, 5, 5, 4, 3), 2, 3), 3)  # bar 2: equal averages
    assert not ma_breakdown(series(5, 5, 5, 5, 5), 2, 3).any()  # equal now is not below


def test_already_below_is_not_a_new_breakdown() -> None:
    assert not ma_breakdown(series(5, 4, 3, 2, 1, 0), 2, 3).iloc[4:].any()


def test_default_five_and_twenty_day_breakdown() -> None:
    close = series(*[100.0] * 20, 90, 90, 90)

    result = ma_breakdown(close)

    # bar 20: ma5 = 98 < ma20 = 99.5 while on bar 19 both were 100
    assert only_true_at(result, 20)


def test_recovery_means_the_short_average_is_back_above_the_long_one() -> None:
    assert flags(ma_recovered(series(1, 2, 3, 4), 2, 3)) == [False, False, True, True]
    assert not ma_recovered(series(5, 5, 5, 5), 2, 3).any()


def test_stock_and_index_use_the_same_rule() -> None:
    close = series(5, 5, 5, 4, 3)

    result = force_sell(close, close, 2, 3)

    assert result["stock"].equals(result["index"])
    assert only_true_at(result["force_sell"], 3)


def test_an_index_breakdown_forces_every_stock_but_a_stock_breakdown_only_itself() -> None:
    falling = series(5, 5, 5, 4, 3)
    steady = series(5, 5, 5, 5, 5)
    stocks = pd.DataFrame({"falls": falling, "steady": steady})

    only_stock = force_sell(stocks, steady, 2, 3)
    assert only_stock["force_sell"].iloc[3].to_dict() == {"falls": True, "steady": False}

    index_falls = force_sell(stocks, falling, 2, 3)
    assert index_falls["force_sell"].iloc[3].to_dict() == {"falls": True, "steady": True}
    assert index_falls["index"].iloc[3].all()
    assert not index_falls["stock"]["steady"].any()


def test_index_days_missing_from_the_stock_calendar_are_ignored() -> None:
    stock = pd.Series([5.0, 5, 5, 5], index=pd.RangeIndex(4))
    index = pd.Series([5.0, 5, 5, 4, 3], index=pd.RangeIndex(5))  # breakdown on bar 3

    assert only_true_at(force_sell(stock, index, 2, 3)["force_sell"], 3)
