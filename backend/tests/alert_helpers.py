"""Helpers that pin the engine's signals, shared by the alert engine and job tests."""

from typing import Any

import pandas as pd
import pytest

from app.engine import alert_signals

SELL_FUNCTIONS = [
    "rsi_overbought_exit",
    "bollinger_upper_reentry",
    "macd_weakening",
    "bearish_divergence",
    "atr_disparity_overheat",
]
REBUY_FUNCTIONS = ["rsi_rebound", "bollinger_support", "macd_golden_cross"]


# --- helpers ----------------------------------------------------------------------------------


def pin(
    monkeypatch: pytest.MonkeyPatch, *, true: set[str] | None = None, flow: str = "off"
) -> None:
    """Force the engine signals: names in ``true`` fire on every bar, the rest never do.

    ``flow``: "off" (no 수급 이탈), "exit" (수급 이탈 holds) or "missing" (no flow data).
    """
    true = true or set()

    def series_stub(name: str) -> Any:
        def stub(first: pd.Series, *args: Any, **kwargs: Any) -> pd.Series:
            return pd.Series(name in true, index=first.index)

        return stub

    for name in [*SELL_FUNCTIONS, *REBUY_FUNCTIONS]:
        monkeypatch.setattr(alert_signals, name, series_stub(name))

    def flow_frame(index: pd.Index) -> pd.DataFrame:
        return pd.DataFrame(
            {"signal": flow == "exit", "unreflected": flow == "missing"}, index=index
        )

    monkeypatch.setattr(
        alert_signals, "flow_exit", lambda foreign, institution, days=3: flow_frame(foreign.index)
    )
    monkeypatch.setattr(
        alert_signals,
        "flow_exit_at_bars",
        lambda foreign, institution, bar_times, days=3: flow_frame(bar_times),
    )


def force_sell_frame(*, stock: bool = False, index: bool = False) -> Any:
    """A stand-in for ``engine.force_sell`` with the A-13 flags fixed."""

    def stub(
        close: pd.Series, index_close: pd.Series, short: int = 5, long: int = 20
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {"stock": stock, "index": index, "force_sell": stock or index}, index=close.index
        )

    return stub
