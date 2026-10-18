import time

import pandas as pd
from sqlalchemy.orm import Session

from app.backtest.candidates import screener_candidates
from app.backtest.config import UniverseOptions
from app.backtest.dataset import Dataset, load_dataset
from app.engine.params import SignalParams
from app.services.screener import compute_signal_table, evaluate_row, signals_on


def truncated(data: Dataset, last: pd.Timestamp) -> Dataset:
    """The same dataset as it was known at the close of ``last``: no later bar exists."""
    keep = data.dates <= last
    return Dataset(
        panel={name: frame.loc[keep] for name, frame in data.panel.items()},
        index=data.index.loc[keep],
        members=data.members.loc[keep],
        names=data.names,
        markets=data.markets,
        first_bar=data.first_bar,
        last_bar=data.last_bar,
        delisted=data.delisted,
        eval_start=data.eval_start,
        eval_end=last,
        notes=data.notes,
    )


def test_candidates_are_the_scanners_own_picks_for_each_day(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions())
    params = SignalParams()
    result = screener_candidates(data, params)

    day = result.days[len(result.days) // 2]
    members = data.members.loc[day]
    assert isinstance(members, pd.Series)
    row = signals_on(compute_signal_table(data.panel, params), day).loc[members[members].index]
    kept, mode, _, _ = evaluate_row(row, params)

    picked = result.selected.loc[day]
    assert isinstance(picked, pd.Series)
    assert set(result.selected.columns[picked.to_numpy()]) == set(kept.index)
    assert result.gate_mode.loc[day] == mode
    assert (result.score.loc[day].dropna().round(2) == kept["score"].round(2)).all()
    assert result.n_candidates.loc[day] == len(kept)


def test_only_members_of_that_day_can_be_candidates(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions())

    result = screener_candidates(data, SignalParams())

    outside = result.selected & ~data.members.loc[result.days]
    assert not outside.any().any()


def test_a_candidate_never_depends_on_a_later_bar(bt_session: Session) -> None:
    """Cut the data at day T: every pick up to T is the same as with the full history."""
    data = load_dataset(bt_session, UniverseOptions())
    params = SignalParams()
    full = screener_candidates(data, params)
    cut = full.days[len(full.days) * 2 // 3]

    early = screener_candidates(truncated(data, cut), params)

    shared = early.days
    pd.testing.assert_frame_equal(early.selected, full.selected.loc[shared])
    pd.testing.assert_frame_equal(early.score, full.score.loc[shared])


def test_there_are_candidates_to_study_and_it_runs_in_seconds(bt_session: Session) -> None:
    data = load_dataset(bt_session, UniverseOptions())

    started = time.monotonic()
    result = screener_candidates(data, SignalParams())

    assert time.monotonic() - started < 20
    assert result.n_candidates.sum() > 0
    assert set(result.gate_mode.unique()) <= {"", "strict", "relaxed", "decline_rank"}
