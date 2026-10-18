"""The portfolio maths behind the signal-quality backtest, with two interchangeable engines.

``VectorbtEngine`` computes trade returns and risk ratios with vectorbt (PRD 10장). vectorbt
1.1.2, the first release that works with pandas 3, needs numba >= 0.66, whose llvmlite has no
wheel for Intel Macs; there ``PandasEngine`` gives the same numbers from the same formulas (the
tests run both wherever vectorbt is installed and demand equal results). The engine used is
recorded in every result.

Conventions shared by both: the year has 252 sessions; a round trip pays the fee and slippage
on each side (the sell tax is folded in as half a fee on each side, which leaves the cost of a
round trip unchanged to first order); every ratio is computed from daily returns.
"""

import importlib.util
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
import pandas as pd

TRADING_DAYS = 252


class PortfolioEngine(Protocol):
    name: str

    def trade_returns(self, paths: np.ndarray, fee: float, slippage: float) -> np.ndarray:
        """Net return of one round trip per column: buy at the first price, sell at the last.

        ``paths`` is (bars, trades): the prices a trade could have been done at, in order. Fees
        and slippage are fractions paid on each side.
        """

    def ratios(self, daily_returns: pd.Series) -> "Ratios":
        """Risk ratios of a daily return series (no risk-free rate)."""


@dataclass(frozen=True, slots=True)
class Ratios:
    total_return: float
    annualized_return: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float  # a negative number: -0.12 is a 12 % fall from the peak

    def as_dict(self) -> dict[str, float]:
        return {
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown": self.max_drawdown,
        }


def _clean(value: float) -> float:
    return float(value) if np.isfinite(value) else float("nan")


class PandasEngine:
    name = "pandas"

    def trade_returns(self, paths: np.ndarray, fee: float, slippage: float) -> np.ndarray:
        entry, exit_ = paths[0], paths[-1]
        factor = (1 - slippage) * (1 - fee) / ((1 + slippage) * (1 + fee))
        return np.asarray(exit_ * factor / entry - 1.0, dtype="float64")

    def ratios(self, daily_returns: pd.Series) -> Ratios:
        r = daily_returns.astype("float64").fillna(0.0)
        if len(r) < 2:
            return Ratios(*([float("nan")] * 6))
        curve = (1 + r).cumprod()
        total = float(curve.iloc[-1] - 1)
        mdd = float((curve / curve.cummax() - 1).min())
        annual = float(curve.iloc[-1] ** (TRADING_DAYS / len(r)) - 1)
        std = float(r.std(ddof=1))
        downside = float(np.sqrt((np.minimum(r, 0) ** 2).mean()))
        with np.errstate(divide="ignore", invalid="ignore"):
            sharpe = r.mean() / std * np.sqrt(TRADING_DAYS) if std > 0 else float("nan")
            sortino = r.mean() / downside * np.sqrt(TRADING_DAYS) if downside > 0 else float("nan")
            calmar = annual / abs(mdd) if mdd < 0 else float("nan")
        return Ratios(total, annual, _clean(sharpe), _clean(sortino), _clean(calmar), mdd)


class VectorbtEngine:
    name = "vectorbt"

    def __init__(self) -> None:
        import vectorbt as vbt

        self._vbt = vbt

    def trade_returns(self, paths: np.ndarray, fee: float, slippage: float) -> np.ndarray:
        vbt = self._vbt
        bars, trades = paths.shape
        prices = pd.DataFrame(paths)
        entries = pd.DataFrame(False, index=prices.index, columns=prices.columns)
        exits = entries.copy()
        entries.iloc[0] = True
        exits.iloc[bars - 1] = True
        portfolio = vbt.Portfolio.from_signals(
            close=prices,
            price=prices,
            entries=entries,
            exits=exits,
            fees=fee,
            slippage=slippage,
            init_cash=100.0,
        )
        return np.asarray(portfolio.total_return().to_numpy(), dtype="float64").reshape(trades)

    def ratios(self, daily_returns: pd.Series) -> Ratios:
        r = daily_returns.astype("float64").fillna(0.0)
        if len(r) < 2:
            return Ratios(*([float("nan")] * 6))
        acc = r.reset_index(drop=True).vbt.returns(  # type: ignore[attr-defined]
            freq="1D", year_freq=f"{TRADING_DAYS} days"
        )
        return Ratios(
            _clean(acc.total()),
            _clean(acc.annualized()),
            _clean(acc.sharpe_ratio()),
            _clean(acc.sortino_ratio()),
            _clean(acc.calmar_ratio()),
            _clean(acc.max_drawdown()),
        )


def vectorbt_available() -> bool:
    return importlib.util.find_spec("vectorbt") is not None


def get_engine(choice: Literal["auto", "vectorbt", "pandas"] = "auto") -> PortfolioEngine:
    """The engine to use: vectorbt when it is installed (``auto``), else the pandas one."""
    if choice == "pandas":
        return PandasEngine()
    if choice == "vectorbt" or (choice == "auto" and vectorbt_available()):
        return VectorbtEngine()
    return PandasEngine()
