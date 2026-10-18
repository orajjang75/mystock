import numpy as np
import pandas as pd

from app.engine.screener_signals import (
    avg_trading_value,
    bollinger_break_history,
    bollinger_reentry,
    bullish_divergence,
    close_above_ma,
    consecutive_net_buy,
    disparity_oversold,
    disparity_pct,
    downwave_high_breakout,
    drawdown_52w_ok,
    drawdown_52w_pct,
    flow_missing,
    liquidity_ok,
    ma_short_above_long,
    macd_golden_cross,
    net_buy_strength,
    net_buy_strength_pct,
    net_buy_turnaround,
    obv_turn_up,
    rsi_cross_up,
    volume_ratio,
    volume_surge,
)
from tests.engine.helpers import flags, only_true_at, series

# --- 안전 필터: 거래대금 ----------------------------------------------------------------------


def test_average_is_nan_until_20_bars_exist() -> None:
    avg = avg_trading_value(pd.Series(range(1, 26), dtype="float64"))

    assert avg.iloc[:19].isna().all()
    assert avg.iloc[19] == sum(range(1, 21)) / 20
    assert avg.iloc[24] == sum(range(6, 26)) / 20


def test_liquidity_threshold_is_inclusive() -> None:
    assert bool(liquidity_ok(series(*[1_000_000_000.0] * 20)).iloc[-1]) is True
    assert bool(liquidity_ok(series(*[999_999_999.0] * 20)).iloc[-1]) is False


def test_liquidity_is_false_without_enough_history() -> None:
    assert not liquidity_ok(series(*[5e9] * 19)).any()


def test_one_old_spike_leaves_the_window() -> None:
    ok = liquidity_ok(series(1e12, *[1e8] * 25))

    assert bool(ok.iloc[19]) is True  # the spike is still inside the window
    assert bool(ok.iloc[20]) is False  # and now it is gone


# --- 바닥 게이트 ------------------------------------------------------------------------------


def test_drawdown_is_measured_against_the_highest_high_of_the_window() -> None:
    high = series(100, 90, 80, 60)
    close = series(95, 85, 70, 55)

    value = drawdown_52w_pct(high, close, window=3)

    assert value.iloc[:2].isna().all()
    assert (
        abs(value.iloc[2] - (-30.0)) < 1e-9
    )  # 70 vs the window high 100 (float noise: -30.000000000000004)
    assert abs(value.iloc[3] - 100 * (55 / 90 - 1)) < 1e-9  # the 100 has left the window


def test_drawdown_threshold_is_inclusive() -> None:
    high = series(100, 90, 80)
    close = series(95, 85, 70)

    assert flags(drawdown_52w_ok(high, close, -30, window=3)) == [False, False, True]
    assert flags(drawdown_52w_ok(high, close, -31, window=3)) == [False, False, False]


def test_disparity_threshold_is_inclusive() -> None:
    close = series(10.4, 10.4, 9.2)  # 3-bar average is exactly 10.0

    assert abs(disparity_pct(close, 3).iloc[2] - (-8.0)) < 1e-9
    assert flags(disparity_oversold(close, -8.0, 3)) == [False, False, True]
    assert flags(disparity_oversold(series(10.4, 10.4, 9.3), -8.0, 3)) == [False, False, False]


def test_bollinger_break_history_looks_back_n_bars_and_needs_pct_b_strictly_below_zero() -> None:
    pct_b = series(0.5, -0.01, 0.2, 0.2, 0.2)

    assert flags(bollinger_break_history(pct_b, lookback=3)) == [False, True, True, True, False]
    assert not bollinger_break_history(series(0.0, 0.5, 0.0), lookback=3).any()  # 0 is not < 0


def test_bollinger_break_history_ignores_missing_percent_b() -> None:
    assert not bollinger_break_history(series(None, None, 0.3)).any()


# --- 반전 -------------------------------------------------------------------------------------


def test_rsi_crossing_up_fires_only_on_29_to_30() -> None:
    assert only_true_at(rsi_cross_up(series(29, 30)), 1)
    assert only_true_at(rsi_cross_up(series(25, 29, 30, 35)), 2)
    assert only_true_at(rsi_cross_up(series(31, 29, 30)), 2)


def test_rsi_staying_at_or_above_30_is_not_a_cross() -> None:
    assert not rsi_cross_up(series(30, 31)).any()  # previous bar is not below 30
    assert not rsi_cross_up(series(35, 40, 50)).any()
    assert not rsi_cross_up(series(29, 29.99)).any()  # still below
    assert not rsi_cross_up(series(None, 30)).any()  # no previous value


def test_bullish_divergence_needs_a_lower_low_in_price_and_a_higher_low_in_rsi() -> None:
    low = series(5, 3, 5, 2, 5, 6)  # swing lows 3 (bar 1) and 2 (bar 3), k = 1
    rsi = series(50, 30, 50, 35, 50, 50)  # RSI at those bars: 30 -> 35

    result = bullish_divergence(low, rsi, k=1, lookback=5)

    assert only_true_at(result, 4, 5)  # known once the second low is confirmed (bar 3 + 1)


def test_bullish_divergence_is_not_there_without_both_conditions() -> None:
    rsi_down = series(50, 30, 50, 25, 50, 50)
    higher_low = series(5, 2, 5, 3, 5, 6)

    assert not bullish_divergence(series(5, 3, 5, 2, 5, 6), rsi_down, k=1, lookback=5).any()
    assert not bullish_divergence(higher_low, series(50, 30, 50, 35, 50, 50), k=1, lookback=5).any()


def test_bullish_divergence_only_looks_back_lookback_bars() -> None:
    low = series(5, 3, 5, 2, 5, 6)
    rsi = series(50, 30, 50, 35, 50, 50)

    # the first swing is at bar 1: 3 bars old at bar 4, 4 bars old at bar 5
    assert only_true_at(bullish_divergence(low, rsi, k=1, lookback=4), 4)
    assert not bullish_divergence(low, rsi, k=1, lookback=3).any()


def test_a_swing_low_is_not_used_before_it_is_confirmed() -> None:
    low = series(5, 3, 5, 2, 5, 6)
    rsi = series(50, 30, 50, 35, 50, 50)

    full = bullish_divergence(low, rsi, k=1, lookback=5)
    truncated = bullish_divergence(low.iloc[:4], rsi.iloc[:4], k=1, lookback=5)

    assert not truncated.any()  # at bar 3 the second low is only a candidate
    assert full.iloc[:4].tolist() == truncated.tolist()  # later bars never change earlier ones


def test_bollinger_reentry_needs_a_previous_bar_below_zero() -> None:
    assert only_true_at(bollinger_reentry(series(-0.1, 0.0)), 1)  # 0 itself counts as back inside
    assert not bollinger_reentry(series(-0.1, -0.01)).any()
    assert not bollinger_reentry(series(0.0, 0.1)).any()


# --- 확인 -------------------------------------------------------------------------------------


def test_macd_golden_cross_fires_only_on_the_first_bar_above_the_signal() -> None:
    macd = series(0, 0, 1, 2)
    signal = series(0, 0, 0, 0)

    assert only_true_at(macd_golden_cross(macd, signal), 2)  # equal counts as "at or below"


def test_macd_golden_cross_needs_the_previous_bar_at_or_below() -> None:
    assert only_true_at(macd_golden_cross(series(1, 2), series(2, 1)), 1)
    assert not macd_golden_cross(series(2, 3), series(1, 1)).any()  # already above
    assert not macd_golden_cross(series(None, 3), series(None, 1)).any()


def test_macd_golden_cross_below_zero_only_option() -> None:
    above_zero = (series(-1, 0.5), series(0, 0))
    below_zero = (series(-1, -0.2), series(0, -0.5))

    assert macd_golden_cross(*above_zero).iloc[1]
    assert not macd_golden_cross(*above_zero, below_zero_only=True).iloc[1]
    assert macd_golden_cross(*below_zero, below_zero_only=True).iloc[1]


def test_close_above_ma_is_a_strict_state() -> None:
    assert flags(close_above_ma(series(1, 2, 3, 4), 3)) == [False, False, True, True]
    assert not close_above_ma(series(3, 3, 3), 3).any()  # equal is not above


def test_short_ma_above_long_ma_is_a_strict_state() -> None:
    assert flags(ma_short_above_long(series(1, 2, 3, 4), 2, 3)) == [False, False, True, True]
    assert not ma_short_above_long(series(3, 3, 3, 3), 2, 3).any()


def test_downwave_breakout_is_true_while_the_close_is_above_the_last_swing_high() -> None:
    high = series(1, 2, 5, 3, 4, 4.5, 5.6, 5.8, 6.0)  # the only swing high is 5 (bar 2, k = 1)
    close = series(1, 2, 4, 3, 4, 4.5, 5.5, 5.7, 5.9)

    result = downwave_high_breakout(close, high, k=1)

    # the swing is confirmed at bar 3; the close first exceeds 5 at bar 6 and stays above
    assert flags(result) == [False] * 6 + [True] * 3


def test_downwave_breakout_uses_the_latest_confirmed_swing_high() -> None:
    high = series(1, 2, 5, 3, 4, 4.5, 6, 5.2)  # a new swing high of 6 is confirmed at bar 7
    close = series(1, 2, 4, 3, 4, 4.5, 5.5, 5.2)

    result = downwave_high_breakout(close, high, k=1)

    assert only_true_at(result, 6)  # at bar 7 the bar to beat is 6, not 5


def test_obv_turn_up_fires_only_when_obv_steps_above_its_average() -> None:
    obv = series(0, 1, 0, 2)  # 2-bar average: nan, .5, .5, 1

    assert only_true_at(obv_turn_up(obv, window=2), 3)


def test_obv_staying_above_its_average_is_not_a_turn() -> None:
    assert not obv_turn_up(series(0, 1, 2, 3, 4), window=2).any()


# --- 거래량 -----------------------------------------------------------------------------------

BULL_OPEN = series(*[10.0] * 20)
BULL_CLOSE = series(*[11.0] * 20)


def with_last_volume(last: float) -> pd.Series:
    return series(*[100.0] * 19, last)


def test_volume_ratio_includes_the_current_bar_in_the_average() -> None:
    assert abs(volume_ratio(with_last_volume(212)).iloc[-1] - 212 / 105.6) < 1e-12


def test_double_volume_boundary() -> None:
    # avg = (1900 + x) / 20, so the ratio reaches 2 at x = 211.11
    assert not volume_surge(with_last_volume(211), BULL_OPEN, BULL_CLOSE).iloc[-1]
    assert volume_surge(with_last_volume(212), BULL_OPEN, BULL_CLOSE).iloc[-1]


def test_triple_volume_boundary() -> None:
    # the ratio reaches 3 at x = 335.29
    assert not volume_surge(with_last_volume(335), BULL_OPEN, BULL_CLOSE, 3.0).iloc[-1]
    assert volume_surge(with_last_volume(336), BULL_OPEN, BULL_CLOSE, 3.0).iloc[-1]


def test_a_down_candle_never_counts_however_big_the_volume() -> None:
    bearish_close = series(*[9.0] * 20)

    assert not volume_surge(with_last_volume(5000), BULL_OPEN, bearish_close).iloc[-1]
    assert not volume_surge(with_last_volume(5000), BULL_OPEN, BULL_OPEN).iloc[-1]  # flat candle


# --- 수급 -------------------------------------------------------------------------------------


def test_consecutive_net_buy_needs_n_positive_days_in_a_row() -> None:
    assert only_true_at(consecutive_net_buy(series(1, 1, 0, 1, 1, 1), 3), 5)
    assert not consecutive_net_buy(series(1, 1, -1, 1, 1), 3).any()
    assert only_true_at(consecutive_net_buy(series(1, 1, 1), 3), 2)


def test_zero_net_buying_does_not_count() -> None:
    assert not consecutive_net_buy(series(1, 0, 1, 1), 3).any()


def test_a_missing_day_breaks_the_streak() -> None:
    assert not consecutive_net_buy(series(1, None, 1, 1), 3).any()
    assert consecutive_net_buy(series(1, None, 1, 1, 1), 3).iloc[-1]


def test_net_buy_strength_is_the_share_of_trading_value() -> None:
    foreign, institution = series(1, 1, 1), series(1, 1, 1)
    trading_value = series(100, 100, 100)

    assert net_buy_strength_pct(foreign, institution, trading_value, 3).iloc[-1] == 2.0
    assert net_buy_strength(foreign, institution, trading_value, 2.0, 3).iloc[-1]  # inclusive
    assert not net_buy_strength(foreign, series(1, 1, 0), trading_value, 2.0, 3).iloc[-1]


def test_net_buy_strength_is_false_when_flow_data_is_missing() -> None:
    result = net_buy_strength(series(5, None, 5), series(5, 5, 5), series(100, 100, 100), 2.0, 3)

    assert not result.any()


def test_net_buy_turnaround_needs_a_positive_window_after_a_non_positive_one() -> None:
    zero = series(0, 0, 0, 0)

    assert only_true_at(net_buy_turnaround(series(-1, -1, 1, 1), zero, window=2), 3)
    # a previous window that sums to exactly 0 still counts as "≤ 0"
    assert net_buy_turnaround(series(-1, 1, 1, 1), zero, window=2).iloc[3]
    assert not net_buy_turnaround(series(-1, -1, 1, 1), zero, window=2).iloc[2]  # sum is 0, not > 0


def test_net_buy_turnaround_adds_foreign_and_institution() -> None:
    result = net_buy_turnaround(series(-3, -3, 2, 2), series(0, 0, 1, 1), window=2)

    assert only_true_at(result, 3)


def test_net_buy_turnaround_needs_ten_bars_by_default() -> None:
    assert net_buy_turnaround(series(*[-1.0] * 5, *[1.0] * 5), series(*[0.0] * 10)).iloc[9]
    assert not net_buy_turnaround(series(*[1.0] * 9), series(*[0.0] * 9)).any()


def test_flow_missing_flags_a_gap_inside_the_lookback() -> None:
    foreign = series(1, None, 1, 1, 1)
    institution = series(1, 1, 1, 1, 1)

    # the first two bars have less than 3 days of history, so they count as missing too
    assert flags(flow_missing(foreign, institution, 3)) == [True, True, True, True, False]
    assert flow_missing(series(1, 1, 1), series(1, None, 1), 3).iloc[2]  # institution gap counts


def test_flow_is_not_missing_once_a_full_complete_window_exists() -> None:
    assert flags(flow_missing(series(1, 1, 1, 1), series(1, 1, 1, 1), 3)) == [
        True,
        True,
        False,
        False,
    ]


def test_wide_frames_are_evaluated_per_column() -> None:
    foreign = pd.DataFrame({"up": [1.0, 1, 1], "gap": [1.0, np.nan, 1]})

    result = consecutive_net_buy(foreign, 3)

    assert result.iloc[2].to_dict() == {"up": True, "gap": False}
