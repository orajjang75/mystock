"""Parameter sensitivity heatmaps (PRD 10장 신뢰성: 최고점이 아니라 주변까지 고르게 좋은 구간).

Each cell reruns the same evaluation with one or two parameters changed, nothing else. Alongside
the raw grid comes its 3x3 neighbourhood mean: a cell is only trusted if its neighbours are good
too, so ``robust_best`` is the best *smoothed* cell, not the best single one.
"""

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.config import (
    BacktestConfig,
    CycleOptions,
    ParamAxis,
    SensitivitySpec,
    resolve_param,
    with_param,
)
from app.backtest.cycle_simulator import simulate_cycles
from app.backtest.dataset import Dataset
from app.backtest.signal_quality import quick_metrics
from app.db.enums import BarLength
from app.engine.params import SignalParams

Evaluate = Callable[[SignalParams], tuple[float, float]]  # -> (metric, samples)


def cycle_metric(metrics: dict[str, Any], name: str) -> float:
    """One number out of a cycle simulation's metrics (NaN when there is nothing to measure)."""
    value = metrics["increase_rate"]["mean"] if name == "mean_increase_rate" else metrics.get(name)
    return float("nan") if value is None else float(value)


def cycle_samples(metrics: dict[str, Any]) -> float:
    return float(metrics["finished"])


def cycle_evaluator(
    data: Dataset,
    length: BarLength,
    options: CycleOptions,
    period: tuple[pd.Timestamp, pd.Timestamp],
    metric: str,
    codes: list[str] | None = None,
) -> Evaluate:
    def evaluate(params: SignalParams) -> tuple[float, float]:
        result = simulate_cycles(data, params, length, options, period, codes=codes)
        return cycle_metric(result.metrics, metric), cycle_samples(result.metrics)

    return evaluate


def signal_quality_evaluator(
    data: Dataset,
    horizon: int,
    slippage: float,
    metric: str,
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> Evaluate:
    def evaluate(params: SignalParams) -> tuple[float, float]:
        numbers = quick_metrics(data, params, horizon, slippage, window)
        return numbers[metric], numbers["n_events"]

    return evaluate


def make_evaluator(
    data: Dataset,
    config: BacktestConfig,
    target: str,
    metric: str,
    *,
    length: BarLength,
    period: tuple[pd.Timestamp, pd.Timestamp],
    codes: list[str] | None = None,
) -> Evaluate:
    if target == "cycle":
        return cycle_evaluator(data, length, config.cycle or CycleOptions(), period, metric, codes)
    quality = config.signal_quality
    horizon = quality.primary_horizon if quality else 5
    return signal_quality_evaluator(data, horizon, 0.001, metric)


def neighbourhood_mean(grid: np.ndarray) -> np.ndarray:
    """Mean of each cell and its existing neighbours, ignoring empty (NaN) cells."""
    rows, cols = grid.shape
    out = np.full(grid.shape, np.nan)
    for r in range(rows):
        for c in range(cols):
            block = grid[max(0, r - 1) : r + 2, max(0, c - 1) : c + 2]
            if np.isfinite(block).any():
                out[r, c] = np.nanmean(block)
    return out


def _clean(value: float) -> float | None:
    return None if not math.isfinite(value) else float(value)


def run_sensitivity(
    base: SignalParams,
    spec: SensitivitySpec,
    evaluate: Evaluate,
    *,
    min_samples: float = 1,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Evaluate every combination of the axes' values."""
    xs = spec.x.values
    ys: list[float | None] = list(spec.y.values) if spec.y else [None]
    values = np.full((len(ys), len(xs)), np.nan)
    samples = np.zeros((len(ys), len(xs)))
    total = len(xs) * len(ys)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            params = with_param(base, spec.x.path, x)
            if spec.y is not None and y is not None:
                params = with_param(params, spec.y.path, y)
            metric, n = evaluate(params)
            values[iy, ix] = metric
            samples[iy, ix] = n
            if progress:
                progress((iy * len(xs) + ix + 1) / total)
    usable = np.where(samples >= min_samples, values, np.nan)
    smooth = neighbourhood_mean(usable)
    out: dict[str, Any] = {
        "target": spec.target,
        "metric": spec.metric,
        "x": _axis(base, spec.x),
        "y": _axis(base, spec.y) if spec.y else None,
        "cells": [[_clean(v) for v in row] for row in values],
        "samples": [[int(n) for n in row] for row in samples],
        "smoothed": [[_clean(v) for v in row] for row in smooth],
        "min_samples": min_samples,
        "best": _argbest(usable, xs, ys),
        "robust_best": _argbest(smooth, xs, ys),
    }
    return out


def _axis(base: SignalParams, axis: ParamAxis) -> dict[str, Any]:
    return {
        "path": axis.path,
        "values": axis.values,
        "default": float(resolve_param(base, axis.path)),
    }


def _argbest(grid: np.ndarray, xs: list[float], ys: list[float | None]) -> dict[str, Any] | None:
    if not np.isfinite(grid).any():
        return None
    iy, ix = np.unravel_index(int(np.nanargmax(grid)), grid.shape)
    return {"x": xs[ix], "y": ys[iy], "value": float(grid[iy, ix])}
