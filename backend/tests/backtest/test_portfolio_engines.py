"""The two portfolio engines agree, and agree with the textbook formulas."""

import numpy as np
import pandas as pd
import pytest

from app.backtest.portfolio import PandasEngine, VectorbtEngine, get_engine, vectorbt_available

needs_vectorbt = pytest.mark.skipif(
    not vectorbt_available(),
    reason="vectorbt is not installed on this platform (uv sync --extra backtest)",
)


def paths(seed: int = 3, bars: int = 6, trades: int = 25) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(100 * np.cumprod(1 + rng.normal(0, 0.02, (bars, trades)), axis=0))


def daily_returns(seed: int = 5, n: int = 400) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0005, 0.01, n), index=pd.bdate_range("2025-01-01", periods=n))


def test_a_trade_return_is_exit_over_entry_after_costs_on_both_sides() -> None:
    prices = np.array([[100.0], [103.0], [110.0]])

    gross = PandasEngine().trade_returns(prices, fee=0.0, slippage=0.0)
    net = PandasEngine().trade_returns(prices, fee=0.001, slippage=0.002)

    assert gross[0] == pytest.approx(0.10)
    assert net[0] == pytest.approx(110 * 0.998 * 0.999 / (100 * 1.002 * 1.001) - 1)
    assert net[0] < gross[0]


def test_ratios_follow_the_usual_definitions_with_252_sessions() -> None:
    r = daily_returns()

    ratios = PandasEngine().ratios(r)

    curve = (1 + r).cumprod()
    assert ratios.total_return == pytest.approx(curve.iloc[-1] - 1)
    assert ratios.max_drawdown == pytest.approx((curve / curve.cummax() - 1).min())
    assert ratios.sharpe == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))
    downside = np.sqrt((np.minimum(r, 0) ** 2).mean())
    assert ratios.sortino == pytest.approx(r.mean() / downside * np.sqrt(252))
    annual = curve.iloc[-1] ** (252 / len(r)) - 1
    assert ratios.annualized_return == pytest.approx(annual)
    assert ratios.calmar == pytest.approx(annual / abs(ratios.max_drawdown))


def test_a_flat_series_has_no_ratios_instead_of_a_crash() -> None:
    ratios = PandasEngine().ratios(pd.Series(np.zeros(50)))

    assert ratios.total_return == 0
    assert np.isnan(ratios.sharpe) and np.isnan(ratios.calmar)


def test_auto_picks_vectorbt_only_where_it_is_installed() -> None:
    assert get_engine("pandas").name == "pandas"
    assert get_engine("auto").name == ("vectorbt" if vectorbt_available() else "pandas")


@needs_vectorbt
@pytest.mark.parametrize(("fee", "slippage"), [(0.0, 0.0), (0.0003, 0.001), (0.0012, 0.003)])
def test_vectorbt_trade_returns_equal_the_pandas_formula(fee: float, slippage: float) -> None:
    prices = paths()

    np.testing.assert_allclose(
        VectorbtEngine().trade_returns(prices, fee, slippage),
        PandasEngine().trade_returns(prices, fee, slippage),
        rtol=0,
        atol=1e-12,
    )


@needs_vectorbt
def test_vectorbt_ratios_equal_the_pandas_ones() -> None:
    r = daily_returns()

    mine, theirs = PandasEngine().ratios(r), VectorbtEngine().ratios(r)

    for name in mine.as_dict():
        assert getattr(theirs, name) == pytest.approx(getattr(mine, name), rel=1e-9), name
