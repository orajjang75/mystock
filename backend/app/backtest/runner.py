"""One ``BacktestConfig`` in, one result out: the pieces of PRD 10장 run in order.

The result has two parts. ``summary`` is small and goes in the run list (headline numbers, what
data was used, whether the sample sizes are enough). ``detail`` holds the tables and curves the
screens draw. Both are plain JSON: ``jsonable`` turns numpy values, timestamps and NaN into
something the database and the API can carry.
"""

import logging
import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.backtest.config import BacktestConfig, CycleOptions, SensitivitySpec
from app.backtest.cycle_simulator import CycleResult, _holdings_at, simulate_cycles
from app.backtest.dataset import BacktestDataError, Dataset, load_dataset
from app.backtest.sensitivity import (
    cycle_evaluator,
    make_evaluator,
    run_sensitivity,
    signal_quality_evaluator,
)
from app.backtest.signal_quality import run_signal_quality
from app.backtest.walk_forward import run_walk_forward
from app.db.enums import BarLength
from app.engine.params import SignalParams

logger = logging.getLogger(__name__)

Progress = Callable[[float, str], None]
LENGTHS = (BarLength.M30, BarLength.M60, BarLength.D1)


def jsonable(value: Any) -> Any:
    """Recursively turn numpy, pandas and date values and NaN/inf into JSON-safe ones."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, pd.Timestamp | datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(jsonable(v) for v in value)
    return value


def cycle_period(
    data: Dataset, config: BacktestConfig, lengths: tuple[BarLength, ...]
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The one period every bar length is run over: where all their data overlap."""
    start = pd.Timestamp(config.start_date) if config.start_date else data.eval_start
    end = pd.Timestamp(config.end_date) if config.end_date else data.eval_end
    end = min(end, data.eval_end)
    if any(length is not BarLength.D1 for length in lengths):
        span = data.intraday_span()
        if span is None:
            raise BacktestDataError(
                "No 30-minute bars are stored, so the cycle cannot be run on minute bars."
            )
        start, end = max(start, span[0]), min(end, span[1])
    if start >= end:
        raise BacktestDataError(f"The period {start.date()} .. {end.date()} is empty.")
    return start, end


def _eligible(data: Dataset, codes: list[str], lengths: tuple[BarLength, ...]) -> list[str]:
    """Stocks that have bars of every length being compared (the same stocks in every run)."""
    ok = []
    for code in codes:
        if all(len(data.bars(code, length)) >= 40 for length in lengths):
            ok.append(code)
    return ok


def _headline(metrics: dict[str, Any]) -> dict[str, Any]:
    """The few numbers of a cycle run that are compared across bar lengths and slippages."""
    return {
        "bar_length": metrics["bar_length"],
        "slippage": metrics["slippage"],
        "stocks": metrics["stocks"],
        "sells": metrics["sells"],
        "finished": metrics["finished"],
        "completed": metrics["completed"],
        "completion_rate": metrics["completion_rate"],
        "gain_rate": metrics["gain_rate"],
        "mean_increase_rate": metrics["increase_rate"]["mean"],
        "median_increase_rate": metrics["increase_rate"]["median"],
        "cumulative_increase": metrics["cumulative_increase"],
        "cumulative_increase_pct": metrics["cumulative_increase_pct"],
        "signal_dates": metrics["signal_dates"],
        "expired": metrics["expired"],
        "total_return": metrics["total_return"],
        "hold_return": metrics["hold_return"],
        "excess_return": metrics["excess_return"],
        "max_drawdown": metrics["max_drawdown"],
        "costs": metrics["costs"],
    }


def _adoption(result: CycleResult, options: CycleOptions) -> dict[str, Any]:
    finished = result.metrics["finished"]
    reasons = []
    if finished < options.min_sample_cycles:
        reasons.append(f"끝난 사이클 {finished}건 < 최소 {options.min_sample_cycles}건: 표본 부족")
    return {
        "adoptable": not reasons,
        "reasons": reasons,
        "min_sample_cycles": options.min_sample_cycles,
    }


def run_cycle_part(data: Dataset, config: BacktestConfig, progress: Progress) -> dict[str, Any]:
    options = config.cycle
    assert options is not None
    params = config.params
    primary = config.bar_length
    lengths = LENGTHS if config.compare_bar_lengths else (primary,)
    period = cycle_period(data, config, lengths)
    start_codes = _holdings_at(data, period[0], options.max_stocks)
    codes = _eligible(data, start_codes, lengths)
    if not codes:
        raise BacktestDataError("No stock has bars of every length being compared.")

    progress(0.0, "cycle: primary run")
    main = simulate_cycles(data, params, primary, options, period, codes=codes)
    adoption = _adoption(main, options)

    slippage_rows = []
    for k, slip in enumerate(options.slippages):
        result = (
            main
            if slip == options.slippage
            else simulate_cycles(data, params, primary, options, period, slippage=slip, codes=codes)
        )
        slippage_rows.append(_headline(result.metrics))
        progress((k + 1) / (len(options.slippages) + 1), f"cycle: slippage {slip:.3%}")

    comparison = []
    if config.compare_bar_lengths:
        for k, length in enumerate(LENGTHS):
            result = (
                main
                if length is primary
                else simulate_cycles(data, params, length, options, period, codes=codes)
            )
            row = _headline(result.metrics)
            row["adoption"] = _adoption(result, options)
            row["forced"] = result.metrics["forced"]["count"]
            comparison.append(row)
            progress((k + 1) / len(LENGTHS), f"cycle: {length.value}")
    return {
        "period": {"start": period[0].date().isoformat(), "end": period[1].date().isoformat()},
        "codes": codes,
        "main": main,
        "adoption": adoption,
        "slippage": slippage_rows,
        "comparison": comparison,
    }


def run_backtest(
    session: Session, config: BacktestConfig, progress: Progress | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run everything the config asks for. Returns ``(summary, detail)``, both JSON-safe."""
    report: Progress = progress or (lambda _f, _m: None)
    report(0.02, "loading data")
    data = load_dataset(session, config.universe, config.start_date, config.end_date)
    summary: dict[str, Any] = {
        "period": {
            "start": data.eval_start.date().isoformat(),
            "end": data.eval_end.date().isoformat(),
        },
        "data": {
            "stocks": len(data.codes),
            "sessions": len(data.dates),
            "delisted": sorted(data.delisted),
            "notes": data.notes,
        },
    }
    detail: dict[str, Any] = {}
    parts = [
        p
        for p in (config.signal_quality, config.cycle, config.sensitivity, config.walk_forward)
        if p
    ]
    done = 0

    def stage(name: str) -> Progress:
        base = 0.05 + 0.9 * done / len(parts)
        width = 0.9 / len(parts)
        return lambda fraction, message: report(base + width * fraction, f"{name}: {message}")

    cycle_part: dict[str, Any] | None = None
    if config.signal_quality:
        report(0.05, "signal quality")
        quality = run_signal_quality(data, config.params, config.signal_quality)
        detail["signal_quality"] = quality
        summary["signal_quality"] = _quality_summary(quality)
        done += 1
    if config.cycle:
        cycle_part = run_cycle_part(data, config, stage("cycle"))
        main: CycleResult = cycle_part["main"]
        summary["cycle"] = {
            "period": cycle_part["period"],
            "stocks": len(cycle_part["codes"]),
            "headline": _headline(main.metrics),
            "adoption": cycle_part["adoption"],
            "comparison": cycle_part["comparison"],
        }
        detail["cycle"] = {
            "period": cycle_part["period"],
            "metrics": main.metrics,
            "cycles": main.cycles,
            "curves": main.curves,
            "notes": main.notes,
            "slippage": cycle_part["slippage"],
            "comparison": cycle_part["comparison"],
        }
        done += 1
    if config.sensitivity:
        detail["sensitivity"] = _run_sensitivity(
            data, config, config.sensitivity, cycle_part, stage("sensitivity")
        )
        done += 1
    if config.walk_forward:
        detail["walk_forward"] = _run_walk_forward(data, config, cycle_part, stage("walk-forward"))
        done += 1
    summary["warnings"] = _warnings(data, summary)
    report(1.0, "done")
    return jsonable(summary), jsonable(detail)


def _quality_summary(quality: dict[str, Any]) -> dict[str, Any]:
    primary = str(quality["primary_horizon"])
    row = quality["horizons"][primary]
    return {
        "engine": quality["engine"],
        "period": quality["period"],
        "horizon": quality["primary_horizon"],
        "candidates": quality["candidates"],
        "strategy": row["strategy"],
        "universe": row["universe"],
        "random": row["random"],
        "kospi": row["kospi"],
        "ratios": quality["portfolios"],
        "adoption": quality["adoption"],
    }


def _period_for(
    cycle_part: dict[str, Any] | None, data: Dataset, target: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The cycle period (where minute bars exist) for a cycle target; the whole evaluation window
    for the daily screener's signal quality."""
    if cycle_part and target == "cycle":
        p = cycle_part["period"]
        return pd.Timestamp(p["start"]), pd.Timestamp(p["end"])
    return data.eval_start, data.eval_end


def _run_sensitivity(
    data: Dataset,
    config: BacktestConfig,
    spec: SensitivitySpec,
    cycle_part: dict[str, Any] | None,
    progress: Progress,
) -> dict[str, Any]:
    period = _period_for(cycle_part, data, spec.target)
    codes = cycle_part["codes"] if cycle_part else None
    evaluate = make_evaluator(
        data, config, spec.target, spec.metric, length=config.bar_length, period=period, codes=codes
    )
    minimum = (
        (config.cycle.min_sample_cycles if config.cycle else 1)
        if spec.target == "cycle"
        else (config.signal_quality.min_sample_dates if config.signal_quality else 1)
    )
    return run_sensitivity(
        config.params,
        spec,
        evaluate,
        min_samples=minimum,
        progress=lambda f: progress(f, f"{f:.0%}"),
    )


def _run_walk_forward(
    data: Dataset, config: BacktestConfig, cycle_part: dict[str, Any] | None, progress: Progress
) -> dict[str, Any]:
    spec = config.walk_forward
    assert spec is not None
    period = _period_for(cycle_part, data, spec.target)
    dates = data.dates[(data.dates >= period[0]) & (data.dates <= period[1])]
    codes = cycle_part["codes"] if cycle_part else None
    options = config.cycle or CycleOptions()
    quality = config.signal_quality
    horizon = quality.primary_horizon if quality else 5

    def evaluate(
        params: SignalParams, window: tuple[pd.Timestamp, pd.Timestamp]
    ) -> tuple[float, float]:
        if spec.target == "cycle":
            return cycle_evaluator(data, config.bar_length, options, window, spec.metric, codes)(
                params
            )
        return signal_quality_evaluator(data, horizon, 0.001, spec.metric, window)(params)

    return run_walk_forward(
        config.params, spec, dates, evaluate, progress=lambda f: progress(f, f"{f:.0%}")
    )


def _warnings(data: Dataset, summary: dict[str, Any]) -> list[str]:
    notes = data.notes
    out = []
    if "universe_warning" in notes:
        out.append(str(notes["universe_warning"]))
    if "warmup_warning" in notes:
        out.append(str(notes["warmup_warning"]))
    if "suspected_unadjusted" in notes:
        out.append("일 변동폭이 상하한(±30%)을 넘는 종목이 있습니다. 수정주가가 아닐 수 있습니다.")
    if not notes.get("include_delisted", True):
        out.append("생존 종목만 썼습니다: 상장폐지 종목이 빠져 결과가 실제보다 좋게 보입니다.")
    for key in ("signal_quality", "cycle"):
        part = summary.get(key)
        if part and not part["adoption"]["adoptable"]:
            out.extend(part["adoption"]["reasons"])
    return out
