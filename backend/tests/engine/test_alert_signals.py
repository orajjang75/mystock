import pandas as pd
import pytest

from app.core.market import KST
from app.engine.alert_signals import (
    atr_disparity,
    atr_disparity_overheat,
    bearish_divergence,
    bollinger_support,
    bollinger_upper_reentry,
    flow_exit,
    flow_exit_at_bars,
    macd_golden_cross,
    macd_weakening,
    price_condition,
    rebuy_decision,
    rebuy_target_price,
    rsi_overbought_exit,
    rsi_rebound,
    sell_decision,
)
from app.engine.indicators import bollinger
from tests.engine.helpers import flags, only_true_at, series

# --- 매도 -------------------------------------------------------------------------------------


def test_rsi_overbought_exit_boundary() -> None:
    assert only_true_at(rsi_overbought_exit(series(70, 69.99)), 1)  # previous 70 counts (>=)
    assert only_true_at(rsi_overbought_exit(series(80, 69)), 1)
    assert not rsi_overbought_exit(series(69, 69.99)).any()  # was never overbought
    assert not rsi_overbought_exit(series(71, 70)).any()  # 70 is not below 70
    assert not rsi_overbought_exit(series(None, 60)).any()


def test_bollinger_upper_reentry_boundary() -> None:
    assert only_true_at(bollinger_upper_reentry(series(1.01, 1.0)), 1)  # back at 1 counts (<=)
    assert only_true_at(bollinger_upper_reentry(series(1.5, 0.9)), 1)
    assert not bollinger_upper_reentry(series(1.0, 0.9)).any()  # previous must be strictly > 1
    assert not bollinger_upper_reentry(series(1.2, 1.01)).any()  # still outside


def test_macd_dead_cross_counts_as_weakening() -> None:
    # previous macd == signal (>=) and macd drops below signal now
    assert only_true_at(macd_weakening(series(1, 0.9), series(1, 1)), 1)
    assert not macd_weakening(series(1, 1), series(1, 1)).any()  # touching is not a cross down
    assert not macd_weakening(series(0.9, 0.8), series(1, 1)).any()  # already below: no new cross


def test_macd_histogram_shrinking_for_n_bars_while_positive_counts_as_weakening() -> None:
    macd, signal = series(4, 3, 2), series(1, 1, 1)  # histogram 3, 2, 1: no cross

    assert only_true_at(macd_weakening(macd, signal, bars=2), 2)  # two decreases in a row
    assert not macd_weakening(macd.iloc[:2], signal.iloc[:2], bars=2).any()  # only one so far


def test_histogram_that_reaches_zero_is_not_positive() -> None:
    assert not macd_weakening(series(3, 2, 1), series(1, 1, 1), bars=2).any()  # histogram 2, 1, 0


def test_a_rising_histogram_is_not_weakening() -> None:
    assert not macd_weakening(series(2, 3, 4), series(1, 1, 1)).any()
    assert not macd_weakening(series(4, 3, 3.5), series(1, 1, 1)).any()  # decrease, then increase


def test_bearish_divergence_needs_a_higher_high_with_a_weaker_rsi() -> None:
    high = series(1, 3, 1, 4, 1, 2)  # swing highs 3 (bar 1) and 4 (bar 3), k = 1
    rsi = series(50, 70, 50, 60, 50, 50)  # RSI at those bars: 70 -> 60
    flat_hist = series(*[0.0] * 6)

    result = bearish_divergence(high, rsi, flat_hist, k=1, lookback=5)

    assert only_true_at(result, 4, 5)


def test_bearish_divergence_is_also_triggered_by_the_macd_histogram_alone() -> None:
    high = series(1, 3, 1, 4, 1, 2)
    rsi_up = series(50, 60, 50, 70, 50, 50)  # RSI confirms the new high
    hist = series(0, 2.0, 0, 1.0, 0, 0)  # histogram at the swings: 2 -> 1, weaker

    assert only_true_at(bearish_divergence(high, rsi_up, hist, k=1, lookback=5), 4, 5)
    assert not bearish_divergence(high, rsi_up, series(0, 1.0, 0, 2.0, 0, 0), k=1).any()


def test_bearish_divergence_needs_a_higher_high() -> None:
    lower_high = series(1, 4, 1, 3, 1, 2)

    assert not bearish_divergence(
        lower_high, series(50, 70, 50, 60, 50, 50), series(*[0.0] * 6), k=1
    ).any()


def test_atr_disparity_boundary() -> None:
    close = series(10, 10, 13)
    atr = series(1, 1, 1)  # 3-bar average of close is 11 -> (13 - 11) / 1 = 2

    assert atr_disparity(close, atr, window=3).iloc[2] == 2.0
    assert not atr_disparity_overheat(close, atr, window=3, multiple=3.0).iloc[2]
    # (14 - 11.33..) / 0.5: exactly on the multiple when the average is 11 and ATR is 2/3
    assert atr_disparity_overheat(close, series(1, 1, 2 / 3), window=3, multiple=3.0).iloc[2]
    assert not atr_disparity_overheat(close, series(1, 1, 0.667), window=3, multiple=3.0).iloc[2]


# --- 수급 이탈 / 수급 필터 ----------------------------------------------------------------------


def test_flow_exit_needs_n_days_of_combined_net_selling_in_a_row() -> None:
    foreign, institution = series(-2, -2, -2, 1), series(1, 1, 1, 1)  # combined -1 -1 -1 +2

    result = flow_exit(foreign, institution, days=3)

    assert flags(result["signal"]) == [False, False, True, False]
    # only the first two bars lack a full 3-day history
    assert flags(result["unreflected"]) == [True, True, False, False]


def test_flow_exit_needs_strictly_negative_net_buying() -> None:
    result = flow_exit(series(-1, -1, 0), series(0, 0, 0), days=3)  # a day of exactly 0

    assert not result["signal"].any()


def test_flow_exit_is_skipped_and_flagged_when_data_is_missing() -> None:
    foreign = series(-1, -1, None, -1)
    institution = series(-1, -1, -1, -1)

    result = flow_exit(foreign, institution, days=2)

    assert flags(result["signal"]) == [False, True, False, False]
    assert flags(result["unreflected"]) == [True, False, True, True]


def test_flow_exit_with_no_data_at_all_is_skipped_and_flagged() -> None:
    nothing = series(None, None, None)

    result = flow_exit(nothing, nothing, days=2)

    assert not result["signal"].any()
    assert result["unreflected"].all()


def kst(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz=KST)


def test_intraday_bars_use_the_previous_confirmed_daily_bar_never_their_own_day() -> None:
    dates = pd.DatetimeIndex(["2026-10-12", "2026-10-13", "2026-10-14"], name="trade_date")
    foreign = pd.Series([-1.0, -1.0, 1.0], index=dates)
    institution = pd.Series([0.0, 0.0, 0.0], index=dates)
    # daily signal (2 days): Mon False, Tue True (Mon+Tue sold), Wed False
    bars = pd.DatetimeIndex(
        [kst("2026-10-12 09:00"), kst("2026-10-13 09:00"), kst("2026-10-13 14:00"),
         kst("2026-10-14 09:00"), kst("2026-10-15 09:00")]
    )  # fmt: skip

    result = flow_exit_at_bars(foreign, institution, bars, days=2)

    # Mon: nothing earlier. Tue: sees Mon (False) even though Tue itself is True.
    # Wed: sees Tue (True). Thu: sees Wed (False).
    assert flags(result["signal"]) == [False, False, False, True, False]
    assert flags(result["unreflected"]) == [True, True, True, False, False]
    assert result.index.equals(bars)


def test_a_gap_in_the_previous_daily_bar_flags_the_intraday_bars_as_unreflected() -> None:
    dates = pd.DatetimeIndex(["2026-10-12", "2026-10-13", "2026-10-14"], name="trade_date")
    foreign = pd.Series([-1.0, None, -1.0], index=dates)
    institution = pd.Series([-1.0, -1.0, -1.0], index=dates)
    bars = pd.DatetimeIndex([kst("2026-10-14 09:00"), kst("2026-10-15 09:00")])

    result = flow_exit_at_bars(foreign, institution, bars, days=2)

    assert flags(result["unreflected"]) == [True, True]
    assert not result["signal"].any()


# --- 매도 알림 판정 (A-2) ----------------------------------------------------------------------


def test_a_sell_alert_needs_two_overlapping_candidates() -> None:
    on = pd.Series([True, False, True])
    off = pd.Series([False, False, True])
    never = pd.Series([False, False, False])

    result = sell_decision([on, off, never, never, never, never])

    assert result["overlap"].tolist() == [1, 0, 2]
    assert flags(result["alert"]) == [False, False, True]


# --- 재매수 -----------------------------------------------------------------------------------


def test_rsi_rebound_boundaries() -> None:
    assert only_true_at(rsi_rebound(series(29, 30)), 1)  # 30 is included
    assert not rsi_rebound(series(49, 50)).any()  # 50 is excluded
    assert only_true_at(rsi_rebound(series(40, 49.9)), 1)
    assert not rsi_rebound(series(20, 25)).any()  # rising but still under 30
    assert not rsi_rebound(series(45, 44)).any()  # falling
    assert not rsi_rebound(series(40, 40)).any()  # flat is not a rebound


def test_bollinger_support_lower_band_boundaries() -> None:
    close = series(*[100.0] * 19, 100.0, 99.0)
    bands = bollinger(close)
    low_touching_band = close.copy()
    low_touching_band.iloc[-2] = bands["lower"].iloc[-2]  # previous bar's low is exactly %B = 0

    assert bollinger_support(low_touching_band, bands).iloc[-1] == (bands["pct_b"].iloc[-1] > 0)


def test_bollinger_support_with_given_bands() -> None:
    bands = pd.DataFrame(
        {"lower": [10.0, 10.0], "upper": [20.0, 20.0], "pct_b": [0.3, 0.2]}
    )  # previous low 10 -> %B 0; the current close %B is 0.2

    assert only_true_at(bollinger_support(series(10, 12), bands), 1)  # prev <= 0, now > 0
    assert not bollinger_support(series(10.5, 12), bands).any()  # previous low %B 0.05 > 0
    flat = bands.assign(pct_b=[0.3, 0.0])
    assert not bollinger_support(series(10, 12), flat).any()  # current %B must be strictly > 0


def test_bollinger_support_at_the_middle_line() -> None:
    bands = pd.DataFrame({"lower": [10.0, 10.0], "upper": [20.0, 20.0], "pct_b": [0.4, 0.6]})

    assert only_true_at(bollinger_support(series(15, 16), bands, level=0.5), 1)  # %B 0.5 -> 0.6
    assert not bollinger_support(series(15, 16), bands, level=0.0).any()  # prev %B 0.5 > 0


def test_macd_golden_cross_is_shared_with_the_screener() -> None:
    from app.engine import screener_signals

    assert macd_golden_cross is screener_signals.macd_golden_cross


def test_price_condition_is_inclusive() -> None:
    assert flags(price_condition(series(99, 100, 101), 100.0)) == [True, True, False]


def test_rebuy_target_price_by_hand() -> None:
    # cost = fee 0.03% + tax 0.18% = 0.21%; gain 1%: 100000 * (1 - 0.0021 - 0.01) = 98790
    assert rebuy_target_price(100_000.0, cost=0.0021, target_gain=0.01) == pytest.approx(98_790.0)
    assert rebuy_target_price(100_000.0, cost=0.0, target_gain=0.0) == 100_000.0


def test_rebuy_target_price_works_on_a_series_of_sell_prices() -> None:
    result = rebuy_target_price(series(100, 200), cost=0.01, target_gain=0.01)

    assert result.tolist() == pytest.approx([98.0, 196.0])


def decision(
    *, price: bool, confirms: tuple[bool, bool, bool], flow_exit: bool
) -> dict[str, object]:
    def row(value: bool) -> pd.Series:
        return pd.Series([value])

    rsi_ok, support_ok, macd_ok = confirms
    result = rebuy_decision(row(price), row(rsi_ok), row(support_ok), row(macd_ok), row(flow_exit))
    return {k: result[k].iloc[0] for k in ("alert", "held_by_flow_filter", "confirmations")}


def test_a_rebuy_alert_needs_the_price_and_two_of_three_confirmations() -> None:
    assert decision(price=True, confirms=(True, True, False), flow_exit=False)["alert"]
    assert decision(price=True, confirms=(False, True, True), flow_exit=False)["alert"]
    assert decision(price=True, confirms=(True, True, True), flow_exit=False)["alert"]
    assert not decision(price=True, confirms=(True, False, False), flow_exit=False)["alert"]


def test_the_price_condition_alone_or_without_the_price_gives_no_alert() -> None:
    assert not decision(price=True, confirms=(False, False, False), flow_exit=False)["alert"]
    assert not decision(price=False, confirms=(True, True, True), flow_exit=False)["alert"]


def test_flow_exit_holds_back_the_alert_and_leaves_a_warning() -> None:
    held = decision(price=True, confirms=(True, True, False), flow_exit=True)

    assert not held["alert"]
    assert held["held_by_flow_filter"]


def test_the_flow_filter_does_not_count_as_a_confirmation() -> None:
    result = decision(price=True, confirms=(True, False, False), flow_exit=True)

    assert result["confirmations"] == 1
    assert not result["alert"]
    assert not result["held_by_flow_filter"]  # nothing to hold back


def test_a_missing_flow_signal_means_the_filter_is_not_applied() -> None:
    skipped = flow_exit(series(None, None), series(None, None), days=2)["signal"]

    result = rebuy_decision(
        pd.Series([True, True]),
        pd.Series([True, True]),
        pd.Series([True, True]),
        pd.Series([False, False]),
        skipped,
    )

    assert result["alert"].all()
