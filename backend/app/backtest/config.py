"""The request of a backtest: what to run, on which data, with which parameters."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import BarLength
from app.engine.params import SignalParams

SIGNAL_QUALITY_METRICS = (
    "median_return",
    "mean_return",
    "win_rate",
    "profit_factor",
    "n_dates",
    "candidates_per_day",
)
CYCLE_METRICS = (
    "mean_increase_rate",
    "completion_rate",
    "gain_rate",
    "cumulative_increase_pct",
    "max_drawdown",
    "excess_return",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseOptions(_Model):
    """PRD 10장 데이터: how the universe is built and whether failed companies are in it."""

    # Use the market-cap ranking of each date (the stored snapshots) instead of today's ranking
    # for the whole period, which would pick stocks that are large *because* they did well.
    point_in_time: bool = True
    # Keep stocks that were delisted before the end (생존편향 방지). Off = survivors only, which
    # flatters every result; offered to measure how much.
    include_delisted: bool = True


class SignalQualityOptions(_Model):
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20])
    primary_horizon: int = 5  # the 후보 선정 후 5거래일 수익률 of PRD 10장
    random_trials: int = Field(20, ge=1, le=200)
    slippages: list[float] = Field(default_factory=lambda: [0.0, 0.001, 0.003])
    min_sample_dates: int = Field(30, ge=1)  # fewer signal days than this: do not adopt
    seed: int = 7
    engine: Literal["auto", "vectorbt", "pandas"] = "auto"

    @field_validator("horizons")
    @classmethod
    def _horizons(cls, value: list[int]) -> list[int]:
        if not value or any(h < 1 or h > 60 for h in value):
            raise ValueError("horizons must be 1..60 trading days")
        return sorted(set(value))

    @field_validator("slippages")
    @classmethod
    def _slippages(cls, value: list[float]) -> list[float]:
        if not value or any(s < 0 or s > 0.05 for s in value):
            raise ValueError("slippages are fractions between 0 and 0.05")
        return sorted(set(value))

    @model_validator(mode="after")
    def _primary_listed(self) -> "SignalQualityOptions":
        if self.primary_horizon not in self.horizons:
            self.horizons = sorted({*self.horizons, self.primary_horizon})
        return self


class CycleOptions(_Model):
    initial_value: float = Field(10_000_000, gt=0)  # 원 held in each stock at the start
    max_stocks: int = Field(30, ge=1, le=300)  # holdings simulated: the largest at the start
    on_expiry: Literal["abandon", "retry"] = "abandon"  # what the user picks at a 만료 알림
    max_retries: int = Field(2, ge=0, le=10)
    warmup_days: int = Field(5, ge=0, le=60)  # trading days before the first trade is allowed
    slippage: float = Field(0.001, ge=0, le=0.05)
    slippages: list[float] = Field(default_factory=lambda: [0.0, 0.001, 0.003])
    min_sample_cycles: int = Field(30, ge=1)  # fewer finished cycles than this: do not adopt


class ParamAxis(_Model):
    """One parameter and the values to try, e.g. ``rebuy.target_gain`` = 0.005, 0.01, 0.015."""

    path: str
    values: list[float] = Field(min_length=2, max_length=15)

    @field_validator("path")
    @classmethod
    def _known(cls, path: str) -> str:
        resolve_param(SignalParams(), path)
        return path


class SensitivitySpec(_Model):
    target: Literal["cycle", "signal_quality"] = "cycle"
    metric: str = "mean_increase_rate"
    x: ParamAxis
    y: ParamAxis | None = None

    @model_validator(mode="after")
    def _metric(self) -> "SensitivitySpec":
        allowed = CYCLE_METRICS if self.target == "cycle" else SIGNAL_QUALITY_METRICS
        if self.metric not in allowed:
            raise ValueError(f"metric for {self.target} must be one of {', '.join(allowed)}")
        return self


class WalkForwardSpec(_Model):
    """Pick the best value of ``param`` on each training window, then judge it on the next one."""

    target: Literal["cycle", "signal_quality"] = "signal_quality"
    metric: str = "median_return"
    param: ParamAxis
    train_days: int = Field(120, ge=20)
    test_days: int = Field(40, ge=5)
    step_days: int = Field(40, ge=5)
    min_samples: int = Field(
        10, ge=1
    )  # a value with fewer samples on the training window is skipped

    @model_validator(mode="after")
    def _metric(self) -> "WalkForwardSpec":
        allowed = CYCLE_METRICS if self.target == "cycle" else SIGNAL_QUALITY_METRICS
        if self.metric not in allowed:
            raise ValueError(f"metric for {self.target} must be one of {', '.join(allowed)}")
        return self


class BacktestConfig(_Model):
    name: str | None = Field(default=None, max_length=80)
    start_date: date | None = None  # default: where the data starts (after the indicator warm-up)
    end_date: date | None = None  # default: the last stored bar
    bar_length: BarLength = BarLength.M60  # the signal bars of the cycle simulation (A-11)
    params: SignalParams = Field(default_factory=SignalParams)
    universe: UniverseOptions = Field(default_factory=UniverseOptions)
    signal_quality: SignalQualityOptions | None = Field(default_factory=SignalQualityOptions)
    cycle: CycleOptions | None = Field(default_factory=CycleOptions)
    compare_bar_lengths: bool = True  # PRD 10장: 30m, 60m and daily over the same period
    sensitivity: SensitivitySpec | None = None
    walk_forward: WalkForwardSpec | None = None

    @model_validator(mode="after")
    def _period(self) -> "BacktestConfig":
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.signal_quality is None and self.cycle is None:
            raise ValueError("run at least one of signal_quality and cycle")
        for what, spec in (("sensitivity", self.sensitivity), ("walk_forward", self.walk_forward)):
            if spec is not None and spec.target == "cycle" and self.cycle is None:
                raise ValueError(f"{what} on the cycle needs the cycle options")
            if spec is not None and spec.target == "signal_quality" and self.signal_quality is None:
                raise ValueError(f"{what} on the signal quality needs the signal_quality options")
        return self


def resolve_param(params: SignalParams, path: str) -> Any:
    """The current value of a dotted parameter path such as ``sell.min_overlap``."""
    node: Any = params
    for part in path.split("."):
        if not hasattr(node, part) or part.startswith("_"):
            raise ValueError(f"unknown parameter {path!r}")
        node = getattr(node, part)
    if isinstance(node, bool) or not isinstance(node, int | float):
        raise ValueError(f"{path!r} is not a numeric parameter")
    return node


def with_param(params: SignalParams, path: str, value: float) -> SignalParams:
    """A copy of ``params`` with one dotted parameter replaced (validated like any other)."""
    current = resolve_param(params, path)
    dump = params.model_dump()
    node = dump
    *parents, leaf = path.split(".")
    for part in parents:
        node = node[part]
    node[leaf] = int(value) if isinstance(current, int) else float(value)
    return SignalParams.model_validate(dump)
