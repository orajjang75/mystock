"""Candidates of the screener on every day of the period, picked by the screener's own code.

``signals_on`` + ``evaluate_row`` are what the daily scan calls for one day; here they are called
for each day of the backtest on the stocks that were in the universe *that day*. The signal table
is computed once on the whole panel by the vectorized engine functions, which only ever look at
earlier bars, so the row of day t holds what was knowable at t's close.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtest.dataset import Dataset
from app.engine.params import SignalParams
from app.services.screener import compute_signal_table, evaluate_row, signals_on


@dataclass(frozen=True)
class Candidates:
    selected: pd.DataFrame  # bool frame(day x code): picked by the scan of that day
    score: pd.DataFrame  # float frame(day x code): the 0-100 score where picked, else NaN
    n_candidates: pd.Series  # picked stocks per day
    gate_mode: pd.Series  # strict | relaxed | decline_rank per day ("" if nobody was eligible)

    @property
    def days(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.selected.index)


def screener_candidates(
    data: Dataset,
    params: SignalParams,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> Candidates:
    """Scan every day of ``start..end`` (default: the dataset's evaluation window)."""
    start = start or data.eval_start
    end = end or data.eval_end
    table = compute_signal_table(data.panel, params)
    days = data.dates[(data.dates >= start) & (data.dates <= end)]
    codes = data.codes
    position = {code: i for i, code in enumerate(codes)}
    picked = np.zeros((len(days), len(codes)), dtype=bool)
    score = np.full((len(days), len(codes)), np.nan)
    modes: list[str] = []
    members = data.members
    for i, day in enumerate(days):
        today = members.loc[day]
        eligible = today.index[today.to_numpy()]
        if len(eligible) == 0:
            modes.append("")
            continue
        row = signals_on(table, day).loc[eligible]
        kept, mode, _, _ = evaluate_row(row, params)
        modes.append(mode)
        where = [position[c] for c in kept.index]
        picked[i, where] = True
        score[i, where] = kept["score"].to_numpy()
    selected = pd.DataFrame(picked, index=days, columns=codes)
    return Candidates(
        selected=selected,
        score=pd.DataFrame(score, index=days, columns=codes),
        n_candidates=pd.Series(picked.sum(axis=1), index=days, name="candidates"),
        gate_mode=pd.Series(modes, index=days, name="gate_mode"),
    )
