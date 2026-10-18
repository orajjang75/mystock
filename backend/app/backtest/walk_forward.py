"""Walk-forward validation (PRD 10장 신뢰성, 리스크 표 과최적화).

The period is cut into rolling windows. On each training window every candidate value of one
parameter is evaluated and the best one is picked; that value is then judged on the test window
that follows, which the choice never saw. The same test windows are also scored with the default
value, so the answer to "does tuning on the past help on the future?" is a plain comparison.
"""

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.config import WalkForwardSpec, resolve_param, with_param
from app.engine.params import SignalParams

WindowEvaluate = Callable[[SignalParams, tuple[pd.Timestamp, pd.Timestamp]], tuple[float, float]]


def make_windows(
    dates: pd.DatetimeIndex, train: int, test: int, step: int
) -> list[tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]]:
    """Rolling (train, test) windows over session dates, each a (first, last) pair."""
    folds = []
    start = 0
    while start + train + test <= len(dates):
        folds.append(
            (
                (dates[start], dates[start + train - 1]),
                (dates[start + train], dates[start + train + test - 1]),
            )
        )
        start += step
    return folds


def _clean(value: float) -> float | None:
    return None if not math.isfinite(value) else float(value)


def run_walk_forward(
    base: SignalParams,
    spec: WalkForwardSpec,
    dates: pd.DatetimeIndex,
    evaluate: WindowEvaluate,
    *,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    folds = make_windows(dates, spec.train_days, spec.test_days, spec.step_days)
    default = float(resolve_param(base, spec.param.path))
    out: dict[str, Any] = {
        "target": spec.target,
        "metric": spec.metric,
        "param": spec.param.path,
        "values": spec.param.values,
        "default": default,
        "train_days": spec.train_days,
        "test_days": spec.test_days,
        "step_days": spec.step_days,
        "folds": [],
    }
    if not folds:
        out["reason"] = (
            f"the period has {len(dates)} sessions; one fold needs "
            f"{spec.train_days + spec.test_days}"
        )
        out["summary"] = None
        return out

    rows = []
    for k, (train, test) in enumerate(folds):
        scored: list[tuple[float, float, float]] = []  # (value, metric, samples)
        for value in spec.param.values:
            metric, n = evaluate(with_param(base, spec.param.path, value), train)
            scored.append((value, metric, n))
        usable = [row for row in scored if row[2] >= spec.min_samples and math.isfinite(row[1])]
        chosen = max(usable, key=lambda row: row[1]) if usable else None
        fixed_metric, fixed_n = evaluate(base, test)
        picked_metric, picked_n = (
            evaluate(with_param(base, spec.param.path, chosen[0]), test)
            if chosen
            else (float("nan"), 0.0)
        )
        rows.append(
            {
                "fold": k + 1,
                "train": [str(train[0].date()), str(train[1].date())],
                "test": [str(test[0].date()), str(test[1].date())],
                "chosen": chosen[0] if chosen else None,
                "train_metric": _clean(chosen[1]) if chosen else None,
                "train_samples": int(chosen[2]) if chosen else 0,
                "test_metric": _clean(picked_metric),
                "test_samples": int(picked_n),
                "default_test_metric": _clean(fixed_metric),
                "default_test_samples": int(fixed_n),
                "train_grid": [
                    {"value": v, "metric": _clean(m), "samples": int(n)} for v, m, n in scored
                ],
            }
        )
        if progress:
            progress((k + 1) / len(folds))
    out["folds"] = rows
    out["summary"] = _summary(rows)
    return out


def _mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return float(np.mean(clean)) if clean else None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    train = _mean([r["train_metric"] for r in rows])
    test = _mean([r["test_metric"] for r in rows])
    default = _mean([r["default_test_metric"] for r in rows])
    chosen = [r["chosen"] for r in rows if r["chosen"] is not None]
    return {
        "folds": len(rows),
        "mean_train_metric": train,
        "mean_test_metric": test,
        "mean_default_test_metric": default,
        "test_minus_default": None if test is None or default is None else test - default,
        "efficiency": None if not train or test is None else test / train,
        "chosen_values": chosen,
        "chosen_changes": len(set(chosen)),  # how stable the pick is from fold to fold
    }
