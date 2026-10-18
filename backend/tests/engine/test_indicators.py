import numpy as np
import pandas as pd
import pytest

from app.engine.indicators import (
    atr,
    bollinger,
    ema,
    macd,
    obv,
    price_pct_b,
    rsi,
    sma,
    true_range,
    wilder,
)
from tests.engine.helpers import series


def assert_series(actual: pd.Series, expected: list[float | None], tol: float = 1e-9) -> None:
    want = np.array([np.nan if v is None else v for v in expected], dtype="float64")
    np.testing.assert_allclose(actual.to_numpy(dtype="float64"), want, rtol=0, atol=tol)


# --- reference implementations: plain loops, straight from the textbook definitions --------


def ref_wilder(values: np.ndarray, length: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    out[length - 1] = values[:length].mean()
    for i in range(length, len(values)):
        out[i] = (out[i - 1] * (length - 1) + values[i]) / length
    return out


def ref_ema(values: np.ndarray, length: int) -> np.ndarray:
    alpha = 2 / (length + 1)
    first = np.flatnonzero(~np.isnan(values))[0] + length - 1
    out = np.full(len(values), np.nan)
    out[first] = values[first - length + 1 : first + 1].mean()
    for i in range(first + 1, len(values)):
        out[i] = (1 - alpha) * out[i - 1] + alpha * values[i]
    return out


def walk(n: int = 300, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))


# --- sma / ema / wilder --------------------------------------------------------------------


def test_sma_is_nan_until_a_full_window() -> None:
    assert_series(sma(series(1, 2, 3, 4, 5), 3), [None, None, 2, 3, 4])


def test_ema_is_seeded_with_the_first_simple_average() -> None:
    # seed = (1+2)/2 = 1.5 at bar 1; alpha = 2/3
    assert_series(ema(series(1, 2, 3, 4), 2), [None, 1.5, 2.5, 3.5])


def test_wilder_smoothing_by_hand() -> None:
    # seed = (3+3+3)/3 = 3 at bar 2; then (prev * 2 + x) / 3
    assert_series(wilder(series(3, 3, 3, 6, 0), 3), [None, None, 3, 4, 8 / 3])


def test_smoothing_matches_the_loop_reference() -> None:
    data = walk()
    np.testing.assert_allclose(wilder(data, 14).to_numpy(), ref_wilder(data.to_numpy(), 14))
    np.testing.assert_allclose(ema(data, 12).to_numpy(), ref_ema(data.to_numpy(), 12))


# --- rsi -----------------------------------------------------------------------------------


def test_rsi_by_hand() -> None:
    # length 3, deltas +1 +1 -1 +1.  bar 3: avg gain 2/3, avg loss 1/3 -> RS 2 -> 66.667
    # bar 4: avg gain (2/3*2/3 + 1)/... = 7/9, avg loss 2/9 -> RS 3.5 -> 77.778
    value = rsi(series(10, 11, 12, 11, 12), 3)

    assert_series(value, [None, None, None, 200 / 3, 100 - 100 / 4.5])


def test_rsi_is_100_without_losses_and_0_without_gains() -> None:
    assert_series(rsi(series(1, 2, 3, 4, 5), 3).iloc[3:], [100, 100])
    assert_series(rsi(series(5, 4, 3, 2, 1), 3).iloc[3:], [0, 0])


def test_rsi_matches_the_loop_reference() -> None:
    data = walk(seed=1)
    delta = data.diff().to_numpy()
    gain = np.where(delta > 0, delta, 0.0)[1:]
    loss = np.where(delta < 0, -delta, 0.0)[1:]
    avg_gain, avg_loss = ref_wilder(gain, 14), ref_wilder(loss, 14)
    expected = np.r_[np.nan, 100 - 100 / (1 + avg_gain / avg_loss)]

    np.testing.assert_allclose(rsi(data, 14).to_numpy(), expected)


def test_rsi_has_its_first_value_after_length_changes() -> None:
    assert rsi(walk(), 14).first_valid_index() == 14


# --- macd ----------------------------------------------------------------------------------


def test_macd_has_macd_signal_and_histogram_columns() -> None:
    result = macd(walk())

    assert list(result.columns) == ["macd", "signal", "hist"]
    pd.testing.assert_series_equal(
        result["hist"], result["macd"] - result["signal"], check_names=False
    )


def test_macd_warm_up() -> None:
    result = macd(walk(), 12, 26, 9)

    assert result["macd"].first_valid_index() == 25
    assert result["signal"].first_valid_index() == 25 + 8


def test_macd_by_hand() -> None:
    # fast 2, slow 3, signal 2 on a straight line 1..6: both EMAs lag by a constant, so the
    # macd line is a constant 0.5 and the histogram is 0 once the signal line exists.
    result = macd(series(1, 2, 3, 4, 5, 6), 2, 3, 2)

    assert_series(result["macd"], [None, None, 0.5, 0.5, 0.5, 0.5])
    assert_series(result["signal"], [None, None, None, 0.5, 0.5, 0.5])
    assert_series(result["hist"], [None, None, None, 0, 0, 0])


def test_macd_matches_the_loop_reference() -> None:
    data = walk(seed=2).to_numpy()
    line = ref_ema(data, 12) - ref_ema(data, 26)
    expected_signal = ref_ema(line, 9)

    result = macd(pd.Series(data))

    np.testing.assert_allclose(result["macd"].to_numpy(), line)
    np.testing.assert_allclose(result["signal"].to_numpy(), expected_signal)


# --- atr -----------------------------------------------------------------------------------


def test_true_range_uses_the_gap_from_the_previous_close() -> None:
    high = series(10, 11, 20)
    low = series(8, 9, 18)
    close = series(9, 10, 19)

    # bar 2 gaps up: max(20-18, |20-10|, |18-10|) = 10
    assert_series(true_range(high, low, close), [2, 2, 10])


def test_atr_by_hand() -> None:
    high = series(10, 11, 12, 13)
    low = series(8, 9, 9, 12)
    close = series(9, 10, 11, 12.5)

    # TR = 2, 2, 3, 2 ; length 2: seed (2+2)/2 = 2, then (2 + 3)/2 = 2.5, (2.5 + 2)/2 = 2.25
    assert_series(atr(high, low, close, 2), [None, 2, 2.5, 2.25])


def test_atr_matches_the_loop_reference() -> None:
    close = walk(seed=3)
    high, low = close + 1.5, close - 1.0
    tr = true_range(high, low, close).to_numpy()

    np.testing.assert_allclose(atr(high, low, close, 14).to_numpy(), ref_wilder(tr, 14))


# --- obv -----------------------------------------------------------------------------------


def test_obv_adds_volume_on_up_days_and_subtracts_on_down_days() -> None:
    assert_series(obv(series(10, 11, 11, 10), series(100, 200, 300, 400)), [0, 200, 200, -200])


# --- bollinger -----------------------------------------------------------------------------


def test_bollinger_by_hand() -> None:
    # window 3, k 2 on 1,2,3: mid 2, population std sqrt(2/3)
    std = np.sqrt(2 / 3)
    bands = bollinger(series(1, 2, 3), 3, 2.0)

    assert list(bands.columns) == ["lower", "mid", "upper", "pct_b", "bandwidth"]
    assert_series(bands["mid"], [None, None, 2])
    assert_series(bands["lower"], [None, None, 2 - 2 * std])
    assert_series(bands["upper"], [None, None, 2 + 2 * std])
    assert_series(bands["pct_b"], [None, None, (3 - (2 - 2 * std)) / (4 * std)])
    assert_series(bands["bandwidth"], [None, None, 4 * std / 2])


def test_percent_b_is_below_zero_under_the_lower_band_and_above_one_over_the_upper() -> None:
    flat_then_drop = series(*([100.0] * 19), 100.0, 80.0)
    flat_then_jump = series(*([100.0] * 19), 100.0, 120.0)

    assert bollinger(flat_then_drop)["pct_b"].iloc[-1] < 0
    assert bollinger(flat_then_jump)["pct_b"].iloc[-1] > 1


def test_percent_b_is_nan_when_the_bands_have_no_width() -> None:
    assert bollinger(series(*([50.0] * 25)))["pct_b"].isna().all()


def test_percent_b_of_a_price_uses_that_bars_own_bands() -> None:
    close = walk(seed=4)
    bands = bollinger(close)

    pd.testing.assert_series_equal(price_pct_b(close, bands), bands["pct_b"], check_names=False)
    assert (price_pct_b(close - 5, bands).dropna() < bands["pct_b"].dropna()).all()


# --- Series and DataFrame inputs agree -------------------------------------------------------


def test_a_wide_frame_gives_the_same_numbers_as_one_stock_at_a_time() -> None:
    wide = pd.DataFrame({"a": walk(seed=5), "b": walk(seed=6)})

    pd.testing.assert_series_equal(rsi(wide)["a"], rsi(wide["a"]), check_names=False)
    bands = bollinger(wide)
    assert isinstance(bands.columns, pd.MultiIndex)
    pd.testing.assert_series_equal(
        bands["pct_b"]["b"], bollinger(wide["b"])["pct_b"], check_names=False
    )
    pd.testing.assert_series_equal(
        macd(wide)["hist"]["a"], macd(wide["a"])["hist"], check_names=False
    )


@pytest.mark.parametrize("fn", [sma, ema, wilder])
def test_smoothers_restart_per_column_when_history_starts_late(fn) -> None:  # type: ignore[no-untyped-def]
    late = walk(40, seed=7)
    late.iloc[:10] = np.nan
    wide = pd.DataFrame({"early": walk(40, seed=8), "late": late})

    pd.testing.assert_series_equal(fn(wide, 5)["late"], fn(late, 5), check_names=False)
