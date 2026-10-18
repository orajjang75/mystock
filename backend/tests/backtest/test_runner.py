"""The whole backtest on the mock market: every part runs, the numbers hang together."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.backtest.config import (
    BacktestConfig,
    CycleOptions,
    ParamAxis,
    SensitivitySpec,
    SignalQualityOptions,
    UniverseOptions,
    WalkForwardSpec,
    resolve_param,
    with_param,
)
from app.backtest.runner import jsonable, run_backtest
from app.db.enums import BarLength
from app.engine.params import SignalParams

FAST = {"random_trials": 3, "horizons": [3, 5]}


def config(**overrides: Any) -> BacktestConfig:
    base: dict[str, Any] = {
        "signal_quality": SignalQualityOptions(**FAST),
        "cycle": CycleOptions(max_stocks=12, min_sample_cycles=5),
    }
    return BacktestConfig(**{**base, **overrides})


@pytest.fixture(scope="module")
def session(bt_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=bt_engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture(scope="module")
def result(session: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    return run_backtest(
        session,
        config(
            sensitivity=SensitivitySpec(
                target="cycle",
                metric="completion_rate",
                x=ParamAxis(path="rebuy.target_gain", values=[0.005, 0.01, 0.02]),
                y=ParamAxis(path="sell.min_overlap", values=[1, 2]),
            ),
            walk_forward=WalkForwardSpec(
                target="signal_quality",
                metric="mean_return",
                param=ParamAxis(path="screener.drawdown_threshold_pct", values=[-20, -30]),
                train_days=100,
                test_days=40,
                step_days=40,
                min_samples=1,
            ),
        ),
    )


def test_every_part_runs_and_the_result_is_plain_json(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    summary, detail = result

    json.dumps(summary)
    json.dumps(detail)
    assert set(summary) >= {"period", "data", "signal_quality", "cycle", "warnings"}
    assert set(detail) == {"signal_quality", "cycle", "sensitivity", "walk_forward"}
    assert summary["data"]["stocks"] > 25
    assert summary["signal_quality"]["engine"] in ("pandas", "vectorbt")
    assert summary["cycle"]["headline"]["stocks"] > 0


def test_the_three_bar_lengths_are_compared_over_the_same_period_and_stocks(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    summary, detail = result

    rows = summary["cycle"]["comparison"]

    assert [r["bar_length"] for r in rows] == ["30m", "60m", "1d"]
    assert len({r["stocks"] for r in rows}) == 1  # the same stocks in each
    for row in rows:
        assert {"completion_rate", "gain_rate", "mean_increase_rate", "cumulative_increase_pct",
                "max_drawdown", "signal_dates", "adoption"} <= set(row)  # fmt: skip
    # the daily run covers the same days, not the whole history
    assert detail["cycle"]["period"]["start"] >= "2026-07-01"
    assert detail["cycle"]["period"]["end"] == "2026-10-16"


def test_the_slippage_sensitivity_reruns_the_cycle_at_each_level(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, detail = result

    rows = detail["cycle"]["slippage"]

    assert [r["slippage"] for r in rows] == [0.0, 0.001, 0.003]
    # the signals do not depend on what is paid, so the same trades are made at every level ...
    assert len({r["sells"] for r in rows}) == 1
    # ... and a worse fill can only cost
    assert rows[0]["total_return"] > rows[1]["total_return"] > rows[2]["total_return"]


def test_the_cycle_detail_has_the_trade_list_and_the_curves(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, detail = result
    cycle = detail["cycle"]

    assert (
        len(cycle["curves"]["times"])
        == len(cycle["curves"]["strategy"])
        == len(cycle["curves"]["hold"])
    )
    assert len(cycle["curves"]["quantity_gain_pct"]) == len(cycle["curves"]["times"])
    assert cycle["curves"]["strategy"][0] == pytest.approx(100, rel=0.01)
    if cycle["cycles"]:
        first = cycle["cycles"][0]
        assert {"code", "state", "sold_at", "sell_price", "sell_quantity", "rebuy_price",
                "quantity_increase", "costs", "expired"} <= set(first)  # fmt: skip
    metrics = cycle["metrics"]
    assert metrics["finished"] >= metrics["completed"]
    assert metrics["max_drawdown"] <= 0


def test_a_run_with_too_few_cycles_is_not_adopted(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    summary, _ = result

    assert summary["cycle"]["adoption"]["min_sample_cycles"] == 5
    if not summary["cycle"]["adoption"]["adoptable"]:
        assert any("표본 부족" in w for w in summary["warnings"])


def test_the_heatmap_has_a_cell_for_every_combination(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, detail = result
    grid = detail["sensitivity"]

    assert grid["x"]["path"] == "rebuy.target_gain" and grid["y"]["path"] == "sell.min_overlap"
    assert len(grid["cells"]) == 2 and len(grid["cells"][0]) == 3
    assert len(grid["samples"]) == 2 and len(grid["smoothed"]) == 2
    assert grid["x"]["default"] == pytest.approx(0.01)
    if grid["robust_best"]:
        assert grid["robust_best"]["x"] in [0.005, 0.01, 0.02]


def test_walk_forward_tests_each_choice_on_a_window_it_never_saw(
    result: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, detail = result
    wf = detail["walk_forward"]

    assert wf["folds"], wf.get("reason")
    for fold in wf["folds"]:
        assert fold["train"][1] < fold["test"][0]  # the test window starts after the training one
        assert fold["chosen"] in (None, -20, -30)
        assert {g["value"] for g in fold["train_grid"]} == {-20, -30}
    assert wf["summary"]["folds"] == len(wf["folds"])


def test_survivors_only_changes_the_data_and_says_so(session: Session) -> None:
    kept, _ = run_backtest(session, config(cycle=None, signal_quality=SignalQualityOptions(**FAST)))
    dropped, _ = run_backtest(
        session,
        config(
            cycle=None,
            signal_quality=SignalQualityOptions(**FAST),
            universe=UniverseOptions(include_delisted=False),
        ),
    )

    assert kept["data"]["stocks"] > dropped["data"]["stocks"]
    assert any("생존 종목만" in w for w in dropped["warnings"])
    assert not any("생존 종목만" in w for w in kept["warnings"])
    assert kept["signal_quality"]["strategy"]["n_events"] != dropped["signal_quality"]["strategy"][
        "n_events"
    ] or (kept["data"]["stocks"] != dropped["data"]["stocks"])


def test_a_fixed_universe_is_reported_as_such(session: Session) -> None:
    summary, _ = run_backtest(
        session,
        config(cycle=None, universe=UniverseOptions(point_in_time=False)),
    )

    assert "고정" in summary["data"]["notes"]["universe"]


def test_a_daily_only_cycle_run_needs_no_minute_bars(session: Session) -> None:
    summary, detail = run_backtest(
        session,
        config(signal_quality=None, bar_length=BarLength.D1, compare_bar_lengths=False),
    )

    assert summary["cycle"]["comparison"] == []
    assert detail["cycle"]["metrics"]["bar_length"] == "1d"


# --- config and helpers ----------------------------------------------------------------------


def test_the_config_rejects_what_cannot_run() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        BacktestConfig(signal_quality=None, cycle=None)
    with pytest.raises(ValidationError, match="unknown parameter"):
        ParamAxis(path="sell.nonsense", values=[1, 2])
    with pytest.raises(ValidationError, match="not a numeric"):
        ParamAxis(path="rebuy", values=[1, 2])
    with pytest.raises(ValidationError, match="metric"):
        SensitivitySpec(
            target="cycle",
            metric="median_return",
            x=ParamAxis(path="sell.min_overlap", values=[1, 2]),
        )
    with pytest.raises(ValidationError, match="needs the cycle options"):
        BacktestConfig(
            cycle=None,
            sensitivity=SensitivitySpec(
                target="cycle", x=ParamAxis(path="sell.min_overlap", values=[1, 2])
            ),
        )
    with pytest.raises(ValidationError, match="before"):
        BacktestConfig(start_date="2026-05-01", end_date="2026-04-01")


def test_a_parameter_can_be_replaced_by_its_dotted_path() -> None:
    params = SignalParams()

    changed = with_param(params, "sell.min_overlap", 3)

    assert resolve_param(changed, "sell.min_overlap") == 3 and isinstance(
        changed.sell.min_overlap, int
    )
    assert resolve_param(with_param(params, "rebuy.target_gain", 0.02), "rebuy.target_gain") == 0.02
    assert params.sell.min_overlap == 2  # the original is untouched
    with pytest.raises(ValueError):
        with_param(params, "sell.sell_fraction", 5.0)  # the model's own limits still apply


def test_jsonable_handles_numpy_dates_and_nan() -> None:
    import numpy as np
    import pandas as pd

    out = jsonable(
        {
            "a": np.float64(1.5),
            "b": float("nan"),
            "c": pd.Timestamp("2026-01-02"),
            "d": {np.int64(3)},
        }
    )

    assert out == {"a": 1.5, "b": None, "c": "2026-01-02T00:00:00", "d": [3]}
    json.dumps(out)
