import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.engine as engine_package
from app.engine import alert_signals, force_sell, indicators, screener_signals, swings
from app.engine.params import DEFAULT_PARAMS, ScreenerParams, SignalParams

ENGINE_DIR = Path(engine_package.__file__).parent
CALCULATION_MODULES = ["indicators", "screener_signals", "alert_signals", "force_sell", "swings"]


@pytest.mark.parametrize("module", CALCULATION_MODULES)
def test_calculation_modules_have_no_python_loops(module: str) -> None:
    tree = ast.parse((ENGINE_DIR / f"{module}.py").read_text(encoding="utf-8"))

    loops = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.For | ast.While)]

    assert loops == [], f"loops in {module}.py at lines {loops}"


def test_defaults_match_the_prd_table() -> None:
    p = DEFAULT_PARAMS

    assert p.screener.min_avg_trading_value == 1_000_000_000
    assert p.screener.drawdown_window == 252
    assert p.screener.drawdown_threshold_pct == -30
    assert p.screener.drawdown_relaxed_threshold_pct == -20
    assert p.screener.disparity_threshold_pct == -8
    assert p.screener.bollinger_break_lookback == 10
    assert p.screener.rsi_cross_level == 30
    assert p.screener.divergence_lookback == 30
    assert (p.screener.macd_cross_below_zero_only, p.screener.volume_multiple) == (False, 2.0)
    assert p.screener.volume_strong_multiple == 3.0
    assert p.screener.flow_consecutive_days == 3
    assert (p.screener.flow_strength_window, p.screener.flow_strength_threshold_pct) == (5, 2.0)
    assert (p.indicators.rsi_period, p.indicators.atr_period) == (14, 14)
    assert (p.indicators.bollinger_window, p.indicators.bollinger_k) == (20, 2.0)
    assert (p.indicators.macd_fast, p.indicators.macd_slow, p.indicators.macd_signal) == (12, 26, 9)
    assert (p.sell.rsi_overbought, p.sell.macd_weak_bars, p.sell.flow_exit_days) == (70, 2, 3)
    assert (p.sell.atr_disparity_multiple, p.sell.min_overlap) == (3.0, 2)
    assert (p.rebuy.rsi_rebound_low, p.rebuy.rsi_rebound_high) == (30, 50)
    assert (p.rebuy.bollinger_support_level, p.rebuy.min_confirmations) == (0.0, 2)
    assert (p.rebuy.expiry_trading_days, p.rebuy.target_gain) == (5, 0.01)
    assert (p.force_sell.ma_short_window, p.force_sell.ma_long_window) == (5, 20)
    assert (p.score.reversal_points, p.score.confirmation_points) == (30, 30)
    assert (p.score.volume_points, p.score.flow_points) == (20, 20)
    assert (p.score.volume_multiple_points, p.score.volume_strong_multiple_points) == (14, 20)
    assert p.sell.sell_fraction == pytest.approx(1 / 3)
    assert (p.scan.min_score, p.scan.few_candidates_action) == (0, "none")
    assert p.scan.few_candidates_threshold == 5


def test_the_rebuy_cost_is_fee_plus_sell_tax() -> None:
    p = DEFAULT_PARAMS.rebuy

    assert p.cost == p.round_trip_fee_rate + p.sell_tax_rate


def test_function_defaults_come_from_the_single_params_model() -> None:
    assert inspect.signature(screener_signals.rsi_cross_up).parameters["level"].default == 30
    assert inspect.signature(alert_signals.rsi_overbought_exit).parameters["level"].default == 70
    assert inspect.signature(indicators.rsi).parameters["length"].default == 14
    assert inspect.signature(swings.last_swing_high).parameters.keys() == {"high", "k"}
    assert inspect.signature(force_sell.ma_breakdown).parameters["short"].default == 5


def test_params_round_trip_through_json_for_the_settings_screen() -> None:
    restored = SignalParams.model_validate_json(DEFAULT_PARAMS.model_dump_json())

    assert restored == DEFAULT_PARAMS
    assert (
        "drawdown_threshold_pct"
        in SignalParams.model_json_schema()["$defs"]["ScreenerParams"]["properties"]
    )


def test_params_reject_unknown_and_invalid_values() -> None:
    with pytest.raises(ValidationError):
        ScreenerParams.model_validate({"drawdown_threshold": -30})  # misspelled key
    with pytest.raises(ValidationError):
        ScreenerParams(flow_consecutive_days=0)
    with pytest.raises(ValidationError):
        ScreenerParams(volume_multiple=-1)
