"""Pins the engine's signals for the browser tests, the way ``tests/alert_helpers.py`` does.

The engine itself is covered by the unit tests; here the signals only have to arrive at the
moments the test chooses, so the screens can be driven through a whole sell/rebuy cycle. The
price condition of a rebuy is *not* pinned: it is decided by the scripted prices.
"""

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from app.engine import alert_signals
from app.services import alert_engine

SELL_FUNCTIONS = [
    "rsi_overbought_exit",
    "bollinger_upper_reentry",
    "macd_weakening",
    "bearish_divergence",
    "atr_disparity_overheat",
]
REBUY_FUNCTIONS = ["rsi_rebound", "bollinger_support", "macd_golden_cross"]


@dataclass
class Pins:
    sell: bool = True  # the sell candidates all fire
    rebuy: bool = True  # the reversal signals all fire (the price condition stays real)
    flow: Literal["off", "exit", "missing"] = "off"  # 일봉 수급 이탈
    force_sell: bool = False  # the A-13 5-day average breakdown of the stock


_installed = False
pins = Pins()


def reset() -> None:
    pins.sell, pins.rebuy, pins.flow, pins.force_sell = True, True, "off", False


def install() -> None:
    """Replace the signal functions once; they read ``pins`` on every call."""
    global _installed
    if _installed:
        return
    _installed = True

    def series_stub(name: str) -> Any:
        def stub(first: pd.Series, *args: Any, **kwargs: Any) -> pd.Series:
            fires = pins.sell if name in SELL_FUNCTIONS else pins.rebuy
            return pd.Series(fires, index=first.index)

        return stub

    for name in [*SELL_FUNCTIONS, *REBUY_FUNCTIONS]:
        setattr(alert_signals, name, series_stub(name))

    def flow_frame(index: pd.Index) -> pd.DataFrame:
        return pd.DataFrame(
            {"signal": pins.flow == "exit", "unreflected": pins.flow == "missing"}, index=index
        )

    alert_signals.flow_exit = lambda foreign, institution, days=3: flow_frame(foreign.index)
    alert_signals.flow_exit_at_bars = lambda foreign, institution, bar_times, days=3: flow_frame(  # type: ignore[assignment]
        bar_times
    )

    def force_sell(
        close: pd.Series, index_close: pd.Series, short: int = 5, long: int = 20
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {"stock": pins.force_sell, "index": False, "force_sell": pins.force_sell},
            index=close.index,
        )

    vars(alert_engine)["force_sell"] = force_sell
