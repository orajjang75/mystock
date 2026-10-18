"""Reshape per-stock frames into one wide frame per field, the layout the engine runs fastest on."""

from collections.abc import Mapping

import pandas as pd


def to_wide(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """``{code: frame with a column per field}`` -> ``{field: frame with a column per code}``.

    Each wide frame is rebuilt from one array: ``concat`` leaves a block per column, which makes
    every later operation several times slower.
    """
    combined = pd.concat(dict(frames), axis=1)
    names = combined.columns.get_level_values(1).unique()
    wide: dict[str, pd.DataFrame] = {}
    for name in names:
        part = pd.DataFrame(combined.xs(name, axis=1, level=1))
        wide[str(name)] = pd.DataFrame(part.to_numpy(), index=part.index, columns=part.columns)
    return wide
