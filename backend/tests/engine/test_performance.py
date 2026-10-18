"""120 stocks x 500 days through every signal in under a second, without loops over stocks."""

import time
from datetime import date
from typing import Any

import pandas as pd

from app.adapters.mock import MockAdapter
from app.engine import alert_signals as alert
from app.engine import screener_signals as scr
from app.engine.force_sell import force_sell
from app.engine.indicators import atr, bollinger, macd, obv, rsi
from app.engine.panel import to_wide
from tests.conftest import END_DATE


def build_panel(adapter: MockAdapter) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    first = date(2020, 1, 1)
    codes = [s.code for s in adapter.stocks][:120]
    frames = {}
    for code in codes:
        daily = adapter.fetch_daily_ohlcv(code, first, END_DATE)
        flow = adapter.fetch_investor_flow(code, first, END_DATE)
        frames[code] = daily.join(flow)
    index = adapter.fetch_index_daily("KOSPI", first, END_DATE)["close"]
    return to_wide(frames), index


def field(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    """One field of a multi-output result (MultiIndex columns) as a wide frame."""
    return pd.DataFrame(frame[name])


def compute_everything(panel: dict[str, pd.DataFrame], index_close: pd.Series) -> dict[str, Any]:
    o, h, low, c, v = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    foreign, institution, value = (
        panel["foreign_net_buy"],
        panel["institution_net_buy"],
        panel["trading_value"],
    )

    rsi14, bands, m, a, ob = rsi(c), bollinger(c), macd(c), atr(h, low, c), obv(c, v)
    pct_b = field(bands, "pct_b")
    out: dict[str, Any] = {}
    out["liquidity"] = scr.liquidity_ok(value)
    out["drawdown"] = scr.drawdown_52w_ok(h, c)
    out["disparity"] = scr.disparity_oversold(c)
    out["bb_break"] = scr.bollinger_break_history(pct_b)
    out["rsi_cross"] = scr.rsi_cross_up(rsi14)
    out["bull_div"] = scr.bullish_divergence(low, rsi14)
    out["bb_reentry"] = scr.bollinger_reentry(pct_b)
    out["macd_gc"] = scr.macd_golden_cross(field(m, "macd"), field(m, "signal"))
    out["above_ma"] = scr.close_above_ma(c)
    out["ma_gap"] = scr.ma_short_above_long(c)
    out["breakout"] = scr.downwave_high_breakout(c, h)
    out["obv"] = scr.obv_turn_up(ob)
    out["vol2"] = scr.volume_surge(v, o, c)
    out["vol3"] = scr.volume_surge(v, o, c, 3.0)
    out["foreign"] = scr.consecutive_net_buy(foreign)
    out["inst"] = scr.consecutive_net_buy(institution)
    out["strength"] = scr.net_buy_strength(foreign, institution, value)
    out["turn"] = scr.net_buy_turnaround(foreign, institution)
    out["flow_missing"] = scr.flow_missing(foreign, institution, 10)
    sell = [
        alert.rsi_overbought_exit(rsi14),
        alert.bollinger_upper_reentry(pct_b),
        alert.macd_weakening(field(m, "macd"), field(m, "signal")),
        alert.bearish_divergence(h, rsi14, field(m, "hist")),
        alert.atr_disparity_overheat(c, a),
        field(alert.flow_exit(foreign, institution), "signal"),
    ]
    out["sell"] = alert.sell_decision(sell)
    support = alert.bollinger_support(low, bands)
    out["rebuy"] = alert.rebuy_decision(
        alert.price_condition(c, alert.rebuy_target_price(c.shift(5))),
        alert.rsi_rebound(rsi14),
        support,
        alert.macd_golden_cross(field(m, "macd"), field(m, "signal")),
        field(alert.flow_exit(foreign, institution), "signal"),
    )
    out["force"] = force_sell(c, index_close)
    return out


def test_all_signals_for_120_stocks_by_500_days_take_under_a_second(
    mock_adapter: MockAdapter,
) -> None:
    panel, index_close = build_panel(mock_adapter)
    assert panel["close"].shape == (500, 120)
    compute_everything(panel, index_close)  # warm-up: imports and first-call overhead

    started = time.perf_counter()
    result = compute_everything(panel, index_close)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"took {elapsed:.2f}s"
    assert result["force"].shape == (500, 360)


def test_the_wide_result_equals_running_each_stock_on_its_own(mock_adapter: MockAdapter) -> None:
    panel, index_close = build_panel(mock_adapter)
    wide = compute_everything(panel, index_close)
    code = panel["close"].columns[3]
    single = compute_everything({k: v[[code]] for k, v in panel.items()}, index_close)

    for name in ("drawdown", "bull_div", "breakout", "obv", "vol2", "strength", "turn"):
        pd.testing.assert_series_equal(
            wide[name][code],
            single[name][code],
            check_names=False,
        )
    pd.testing.assert_series_equal(
        wide["sell"]["overlap"][code],
        single["sell"]["overlap"][code],
        check_names=False,
    )


def test_some_signals_actually_fire_on_the_mock_market(mock_adapter: MockAdapter) -> None:
    panel, index_close = build_panel(mock_adapter)

    result = compute_everything(panel, index_close)

    for name in ("drawdown", "bb_break", "above_ma", "vol2", "foreign", "turn", "bull_div"):
        assert result[name].to_numpy().any(), name
