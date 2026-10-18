import numpy as np
import pandas as pd


def series(*values: float | None) -> pd.Series:
    """A float Series indexed 0..n-1; ``None`` becomes NaN."""
    return pd.Series([np.nan if v is None else v for v in values], dtype="float64")


def flags(result: pd.Series) -> list[bool]:
    """Boolean Series as a plain list, for readable assertions."""
    return [bool(v) for v in result]


def only_true_at(result: pd.Series, *positions: int) -> bool:
    """True when the signal fires at exactly the given positions and nowhere else."""
    return [i for i, v in enumerate(result) if v] == list(positions)
