"""The sell and rebuy decisions of the holding alerts (PRD 5장 A-2, A-5), for every bar at once.

The live alert engine reads the last row of these frames; the cycle backtest reads all of them,
so the two can never disagree. Everything is built from the pure functions of ``alert_signals``
(called through the module, so a test can swap one out) and ``indicators``: no formula lives
here, only the wiring of the six sell candidates and the three rebuy confirmations.
"""

import pandas as pd

from app.engine import alert_signals as alert
from app.engine.indicators import atr, bollinger, fields, macd, rsi
from app.engine.params import SignalParams

SELL_CANDIDATES = [
    "rsi_overbought_exit",
    "bollinger_upper_reentry",
    "macd_weakening",
    "bearish_divergence",
    "atr_disparity_overheat",
    "flow_exit",
]
REBUY_CONFIRMATIONS = ["rsi_rebound", "bollinger_support", "macd_golden_cross"]
# The order in which the rebuy evidence names its signals.
REBUY_PARTS = ["price_condition", *REBUY_CONFIRMATIONS]


def flow_for_bars(
    foreign: pd.Series,
    institution: pd.Series,
    bar_times: pd.DatetimeIndex,
    *,
    daily: bool,
    days: int,
) -> pd.DataFrame:
    """수급 이탈 (``signal``, ``unreflected``) for each signal bar.

    Daily signal bars use the flow through their own day; intraday bars see the previous
    confirmed daily bar only, never the unfinished day.
    """
    if daily:
        return alert.flow_exit(foreign, institution, days)
    return alert.flow_exit_at_bars(foreign, institution, bar_times, days)


def sell_signals(bars: pd.DataFrame, flow: pd.DataFrame, params: SignalParams) -> pd.DataFrame:
    """A-2 sell candidates at every bar, with the overlap count and the ``alert`` decision.

    ``bars`` has open..volume of the signal length; ``flow`` is ``flow_for_bars`` aligned to it.
    Columns: the six ``SELL_CANDIDATES``, ``overlap``, ``alert`` and the evidence values ``rsi``
    and ``pct_b``.
    """
    ind, sell = params.indicators, params.sell
    close, high, low = bars["close"], bars["high"], bars["low"]
    rsi_value = rsi(close, ind.rsi_period)
    bands = bollinger(close, ind.bollinger_window, ind.bollinger_k)
    lines = macd(close, ind.macd_fast, ind.macd_slow, ind.macd_signal)
    candidates = {
        "rsi_overbought_exit": alert.rsi_overbought_exit(rsi_value, sell.rsi_overbought),
        "bollinger_upper_reentry": alert.bollinger_upper_reentry(
            bands["pct_b"], sell.bollinger_upper_level
        ),
        "macd_weakening": alert.macd_weakening(lines["macd"], lines["signal"], sell.macd_weak_bars),
        "bearish_divergence": alert.bearish_divergence(
            high, rsi_value, lines["hist"], sell.swing_confirm_bars, sell.divergence_lookback
        ),
        "atr_disparity_overheat": alert.atr_disparity_overheat(
            close,
            atr(high, low, close, ind.atr_period),
            sell.atr_disparity_window,
            sell.atr_disparity_multiple,
        ),
        "flow_exit": flow["signal"],
    }
    decision = alert.sell_decision(list(candidates.values()), sell.min_overlap)
    return fields(
        {
            **candidates,
            "overlap": decision["overlap"],
            "alert": decision["alert"],
            "rsi": rsi_value,
            "pct_b": bands["pct_b"],
        }
    )


def rebuy_confirmations(
    bars: pd.DataFrame, flow: pd.DataFrame, params: SignalParams
) -> pd.DataFrame:
    """The three reversal confirmations of A-5 and the flow filter, at every bar.

    They do not depend on the cycle, so a backtest computes them once per stock; the price
    condition (which depends on each cycle's target) is added by ``rebuy_signals``.
    """
    ind, rebuy = params.indicators, params.rebuy
    close, low = bars["close"], bars["low"]
    rsi_value = rsi(close, ind.rsi_period)
    bands = bollinger(close, ind.bollinger_window, ind.bollinger_k)
    lines = macd(close, ind.macd_fast, ind.macd_slow, ind.macd_signal)
    return fields(
        {
            "rsi_rebound": alert.rsi_rebound(
                rsi_value, rebuy.rsi_rebound_low, rebuy.rsi_rebound_high
            ),
            "bollinger_support": alert.bollinger_support(low, bands, rebuy.bollinger_support_level),
            "macd_golden_cross": alert.macd_golden_cross(lines["macd"], lines["signal"]),
            "flow_exit": flow["signal"],
            "flow_unreflected": flow["unreflected"],
        }
    )


def rebuy_signals(
    close: pd.Series, confirmations: pd.DataFrame, target: float, params: SignalParams
) -> pd.DataFrame:
    """A-5 rebuy decision at every bar for a cycle whose 재매수 목표가 is ``target``.

    Columns: ``price_condition``, the three confirmations, ``confirmations`` (count), ``alert``
    and ``held_by_flow_filter`` (the conditions held but 수급 이탈 holds the alert back).
    """
    price_ok = alert.price_condition(close, target)
    decision = alert.rebuy_decision(
        price_ok,
        confirmations["rsi_rebound"],
        confirmations["bollinger_support"],
        confirmations["macd_golden_cross"],
        confirmations["flow_exit"],
        params.rebuy.min_confirmations,
    )
    return fields(
        {
            "price_condition": price_ok,
            "rsi_rebound": confirmations["rsi_rebound"],
            "bollinger_support": confirmations["bollinger_support"],
            "macd_golden_cross": confirmations["macd_golden_cross"],
            "confirmations": decision["confirmations"],
            "alert": decision["alert"],
            "held_by_flow_filter": decision["held_by_flow_filter"],
        }
    )
