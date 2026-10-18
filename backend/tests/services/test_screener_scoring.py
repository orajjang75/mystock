"""Gate and score arithmetic of the screener on hand-made signal rows (no database)."""

import pandas as pd
import pytest

from app.engine.params import ScoreParams, SignalParams
from app.services.screener import (
    CONFIRMATION,
    FLOW,
    REVERSAL,
    apply_gate,
    score_rows,
    select_candidates,
    tags_for,
)

ALL_SIGNALS = [
    *REVERSAL,
    *CONFIRMATION,
    *FLOW,
    "volume_2x",
    "volume_3x",
    "flow_unreflected",
    "liquidity",
    "disparity",
    "bollinger_break",
]


def rows(**stocks: dict[str, object]) -> pd.DataFrame:
    """One row per stock; any signal not given is False. ``drawdown_pct`` defaults to -35."""
    frame = pd.DataFrame(
        {
            name: {code: values.get(name, False) for code, values in stocks.items()}
            for name in ALL_SIGNALS
        }
    )
    frame.index = list(stocks)
    frame["drawdown_pct"] = pd.Series(
        [values.get("drawdown_pct", -35.0) for values in stocks.values()], index=frame.index
    )
    return frame.astype(dict.fromkeys(ALL_SIGNALS, bool))


def score_of(**signals: object) -> float:
    return float(score_rows(rows(stock=signals), ScoreParams())["score"].iloc[0])


def on(*names: str) -> dict[str, object]:
    return dict.fromkeys(names, True)


# --- score ------------------------------------------------------------------------------------


def test_points_per_signal_before_flow_rescaling() -> None:
    # flow data present: the denominator is the full 100
    assert score_of(**on("rsi_cross_up")) == 10
    assert score_of(**on(*REVERSAL)) == 30
    assert score_of(**on("macd_golden_cross")) == 6
    assert score_of(**on(*CONFIRMATION)) == 30
    assert score_of(**on("foreign_consecutive")) == 5
    assert score_of(**on(*FLOW)) == 20


def test_volume_is_14_points_at_2x_and_20_at_3x() -> None:
    assert score_of(**on("volume_2x")) == 14
    assert score_of(**on("volume_2x", "volume_3x")) == 20
    assert score_of(**on("volume_3x")) == 20  # the 3x tier replaces the 2x tier, it does not add


def test_all_signals_give_exactly_100() -> None:
    everything = on(*REVERSAL, *CONFIRMATION, *FLOW, "volume_2x", "volume_3x")

    assert score_of(**everything) == 100
    assert score_of() == 0


def test_without_flow_data_the_score_is_rescaled_to_100() -> None:
    # only 80 points are possible without the flow section, so 62 earned -> 77.5
    base = on(*REVERSAL, "volume_3x", "macd_golden_cross", "close_above_ma20")  # 30 + 20 + 12 = 62
    result = score_rows(rows(stock={**base, "flow_unreflected": True}), ScoreParams())

    assert result["max_points"].iloc[0] == 80
    assert result["score"].iloc[0] == pytest.approx(100 * 62 / 80)


def test_flow_signals_do_not_count_when_flow_is_unreflected() -> None:
    # even if stale flow signals were True, an unreflected day earns nothing from that section
    inputs = {**on(*FLOW), "flow_unreflected": True, **on("rsi_cross_up")}

    result = score_rows(rows(stock=inputs), ScoreParams())

    assert result["flow"].iloc[0] == 0
    assert result["score"].iloc[0] == pytest.approx(100 * 10 / 80)


def test_a_perfect_stock_without_flow_data_is_still_100() -> None:
    everything = on(*REVERSAL, *CONFIRMATION, "volume_3x", "flow_unreflected")

    assert score_of(**everything) == 100


def test_weights_can_be_changed_and_the_total_stays_on_a_100_scale() -> None:
    heavy_reversal = ScoreParams(
        reversal_points=60, confirmation_points=20, volume_points=10, flow_points=10
    )

    one_reversal = score_rows(rows(stock=on("rsi_cross_up")), heavy_reversal)["score"].iloc[0]
    everything = on(*REVERSAL, *CONFIRMATION, *FLOW, "volume_3x")
    full = score_rows(rows(stock=everything), heavy_reversal)["score"].iloc[0]

    assert one_reversal == pytest.approx(100 * 20 / 100)
    assert full == 100


def test_weights_that_do_not_sum_to_100_are_normalised() -> None:
    doubled = ScoreParams(
        reversal_points=60, confirmation_points=60, volume_points=40, flow_points=40
    )

    assert score_rows(rows(stock=on(*REVERSAL)), doubled)["score"].iloc[0] == 30


def test_a_zero_total_weight_scores_zero_instead_of_dividing_by_zero() -> None:
    nothing = ScoreParams(reversal_points=0, confirmation_points=0, volume_points=0, flow_points=0)

    assert score_rows(rows(stock=on(*REVERSAL)), nothing)["score"].iloc[0] == 0


def test_volume_tier_points_follow_the_configured_ratio() -> None:
    tiers = ScoreParams(
        volume_points=20, volume_multiple_points=10, volume_strong_multiple_points=20
    )

    assert score_rows(rows(stock=on("volume_2x")), tiers)["score"].iloc[0] == 10


# --- gate -------------------------------------------------------------------------------------


def gate_of(**signals: object) -> bool:
    frame = rows(stock={"liquidity": True, **signals})
    return bool(apply_gate(frame, SignalParams()).iloc[0])


def test_the_gate_needs_the_drawdown_and_one_of_disparity_or_bollinger_break() -> None:
    assert gate_of(disparity=True)
    assert gate_of(bollinger_break=True)
    assert gate_of(disparity=True, bollinger_break=True)
    assert not gate_of()  # drawdown alone is not enough
    assert not gate_of(disparity=True, drawdown_pct=-29.99)
    assert not gate_of(bollinger_break=True, drawdown_pct=-10.0)


def test_the_drawdown_threshold_is_inclusive() -> None:
    assert gate_of(disparity=True, drawdown_pct=-30.0)
    assert not gate_of(disparity=True, drawdown_pct=-29.999)


def test_a_missing_drawdown_fails_the_gate() -> None:
    assert not gate_of(disparity=True, drawdown_pct=float("nan"))


def test_the_safety_filter_is_part_of_the_gate() -> None:
    frame = rows(stock={"liquidity": False, "disparity": True})

    assert not apply_gate(frame, SignalParams()).iloc[0]


def few_candidate_frame() -> pd.DataFrame:
    return rows(
        deep={"liquidity": True, "disparity": True, "drawdown_pct": -35.0},
        mild={"liquidity": True, "disparity": True, "drawdown_pct": -25.0},
        milder={"liquidity": True, "bollinger_break": True, "drawdown_pct": -21.0},
        shallow={"liquidity": True, "disparity": True, "drawdown_pct": -10.0},
        illiquid={"liquidity": False, "disparity": True, "drawdown_pct": -40.0},
    )


def params_with(action: str, threshold: int = 3, top_n: int = 2) -> SignalParams:
    return SignalParams.model_validate(
        {
            "scan": {
                "few_candidates_action": action,
                "few_candidates_threshold": threshold,
                "decline_rank_top_n": top_n,
            }
        }
    )


def test_by_default_few_candidates_change_nothing() -> None:
    mask, mode, threshold = select_candidates(few_candidate_frame(), params_with("none"))

    assert (mode, threshold) == ("strict", -30.0)
    assert list(mask[mask].index) == ["deep"]


def test_enough_candidates_keep_the_strict_gate_even_with_an_action_configured() -> None:
    mask, mode, _ = select_candidates(few_candidate_frame(), params_with("relax_drawdown", 1))

    assert mode == "strict"
    assert list(mask[mask].index) == ["deep"]


def test_relaxing_the_drawdown_widens_the_gate_to_minus_20() -> None:
    mask, mode, threshold = select_candidates(few_candidate_frame(), params_with("relax_drawdown"))

    assert (mode, threshold) == ("relaxed", -20.0)
    assert list(mask[mask].index) == ["deep", "mild", "milder"]


def test_ranking_by_decline_takes_the_deepest_drawdowns_among_liquid_stocks() -> None:
    mask, mode, threshold = select_candidates(few_candidate_frame(), params_with("rank_by_decline"))

    assert (mode, threshold) == ("decline_rank", None)
    assert list(mask[mask].index) == ["deep", "mild"]  # not the illiquid -40%


# --- tags -------------------------------------------------------------------------------------


def test_tags_list_the_conditions_in_display_order() -> None:
    frame = rows(
        stock={
            **on("disparity", "rsi_cross_up", "macd_golden_cross", "volume_2x", "volume_3x"),
            **on("foreign_consecutive", "net_buy_turnaround"),
        }
    )
    frame["drawdown_met"] = True

    assert tags_for(frame.iloc[0]) == [
        "drawdown",
        "disparity",
        "rsi_cross_up",
        "macd_golden_cross",
        "volume_3x",
        "foreign_consecutive",
        "net_buy_turnaround",
    ]


def test_the_flow_unreflected_tag_comes_last() -> None:
    frame = rows(stock={"flow_unreflected": True, "rsi_cross_up": True})
    frame["drawdown_met"] = False

    assert tags_for(frame.iloc[0]) == ["rsi_cross_up", "flow_unreflected"]
