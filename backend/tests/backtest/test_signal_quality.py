"""Signal quality: the maths on small arrays, the no-lookahead guarantee, and a run on the mock."""

from collections.abc import Iterator
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.backtest.candidates import screener_candidates
from app.backtest.config import SignalQualityOptions, UniverseOptions
from app.backtest.dataset import Dataset, load_dataset
from app.backtest.portfolio import PandasEngine, vectorbt_available
from app.backtest.signal_quality import (
    Events,
    daily_portfolio_returns,
    event_paths,
    event_table,
    events_from,
    index_daily_returns,
    market_regime,
    open_prices,
    quick_metrics,
    random_events,
    run_signal_quality,
    summarize,
    symmetric_fee,
    universe_daily_returns,
)
from app.engine.params import SignalParams

# --- the maths on arrays small enough to check by hand ---------------------------------------


def test_the_entry_is_the_open_of_the_day_after_the_signal_and_the_exit_h_sessions_later() -> None:
    #            day0  day1  day2  day3  day4  day5
    opens = np.array([[10.0], [11.0], [12.0], [13.0], [14.0], [15.0]])
    events = Events(day=np.array([1]), code=np.array([0]))  # signalled on day 1's close

    paths, valid = event_paths(opens, events, horizon=3)

    assert valid.tolist() == [True]
    assert paths[:, 0].tolist() == [12.0, 13.0, 14.0, 15.0]  # day 2's open ... day 5's open
    assert 11.0 not in paths  # nothing from the signal day itself


def test_an_event_without_all_its_prices_is_not_valid() -> None:
    opens = np.array([[10.0], [11.0], [np.nan], [13.0], [14.0]])

    _, too_late = event_paths(opens, Events(np.array([3]), np.array([0])), horizon=2)
    _, has_gap = event_paths(opens, Events(np.array([0]), np.array([0])), horizon=2)

    assert too_late.tolist() == [False]  # the exit would be after the last bar
    assert has_gap.tolist() == [False]


def test_a_gap_up_is_paid_for_not_assumed_away() -> None:
    """The signal day closes at 100 and the next open gaps to 110: the buy is at 110."""
    opens = np.array([[100.0], [100.0], [110.0], [121.0]])  # day 1 closes ~100; day 2 opens 110
    events = Events(np.array([1]), np.array([0]))

    paths, valid = event_paths(opens, events, horizon=1)
    net = PandasEngine().trade_returns(paths[:, valid], 0.0, 0.0)

    assert net[0] == pytest.approx(121 / 110 - 1)  # not 121 / 100 - 1


def test_summary_statistics() -> None:
    returns = np.array([0.10, -0.05, 0.02, -0.01, 0.04, 0.0])
    day = np.array([1, 1, 2, 3, 3, 4])

    s = summarize(returns, day)

    assert (s["n_events"], s["n_dates"]) == (6, 4)
    assert s["mean"] == pytest.approx(returns.mean())
    assert s["median"] == pytest.approx(0.01)
    assert s["win_rate"] == pytest.approx(3 / 6)
    assert s["avg_win"] == pytest.approx((0.10 + 0.02 + 0.04) / 3)
    assert s["payoff_ratio"] == pytest.approx(((0.10 + 0.02 + 0.04) / 3) / (0.06 / 2))
    assert s["profit_factor"] == pytest.approx(0.16 / 0.06)
    # events of one day are averaged before the spread across days is read
    assert s["clustered_mean"] == pytest.approx(np.mean([0.025, 0.02, 0.015, 0.0]))


def test_nothing_to_summarize_is_an_empty_summary() -> None:
    assert summarize(np.array([]), np.array([])) == {"n_events": 0, "n_dates": 0}


def test_the_intervals_of_an_event_compound_to_its_net_trade_return() -> None:
    opens = np.array([[100.0], [100.0], [102.0], [101.0], [105.0], [110.0]])
    events = Events(np.array([0]), np.array([0]))
    paths, valid = event_paths(opens, events, horizon=3)
    net = PandasEngine().trade_returns(paths[:, valid], 0.001, 0.001)

    daily = daily_portfolio_returns(opens, events, 3, net, valid, n_days=6)

    assert np.prod(1 + daily[1:4]) - 1 == pytest.approx(net[0])  # days 1, 2 and 3 are held
    assert daily[0] == 0 and daily[4] == 0 and daily[5] == 0  # cash outside the position


def test_overlapping_events_share_the_day_equally() -> None:
    opens = np.array(
        [[100.0, 100.0], [100.0, 100.0], [110.0, 100.0], [110.0, 100.0], [110.0, 100.0]]
    )
    events = Events(np.array([0, 0]), np.array([0, 1]))
    paths, valid = event_paths(opens, events, horizon=2)
    net = PandasEngine().trade_returns(paths, 0.0, 0.0)

    daily = daily_portfolio_returns(opens, events, 2, net, valid, n_days=5)

    assert daily[1] == pytest.approx((0.10 + 0.0) / 2)  # one stock rose 10 %, the other did not


def test_the_universe_baseline_is_the_equal_weight_open_to_open_return() -> None:
    # decided on day d from the members of day d, held from day d+1's open to day d+2's open
    opens = np.array([[10.0, 20.0], [10.0, 20.0], [11.0, 20.0], [11.0, 22.0]])
    members = np.array([[True, True], [True, False], [True, True], [True, True]])

    daily = universe_daily_returns(opens, members)

    # labelled by the day the position is opened (d+1): day 1 holds both stocks of day 0
    assert daily[1] == pytest.approx((0.10 + 0.0) / 2)
    # day 2 holds the members of day 1: only the first stock, which did not move
    assert daily[2] == pytest.approx(0.0)  # the second stock's +10 % (day 2 -> 3) is not counted
    assert daily[0] == 0 and daily[3] == 0


def test_the_index_baseline_uses_the_same_timing() -> None:
    daily = index_daily_returns(np.array([100.0, 100.0, 102.0, 102.0]))

    assert daily.tolist() == pytest.approx([0.0, 0.02, 0.0, 0.0])


def test_random_entries_match_the_number_of_picks_and_stay_inside_the_universe() -> None:
    members = np.zeros((6, 8), dtype=bool)
    members[:, :5] = True
    members[3, :2] = False
    per_day = np.array([0, 2, 1, 4, 0, 9])

    events = random_events(members, per_day, first=1, rng=np.random.default_rng(1))

    counts = np.bincount(events.day, minlength=6)
    assert counts.tolist() == [0, 2, 1, 3, 0, 5]  # capped by the members available that day
    assert members[events.day, events.code].all()
    again = random_events(members, per_day, first=1, rng=np.random.default_rng(1))
    assert (again.day == events.day).all() and (again.code == events.code).all()


def test_the_market_regime_follows_the_index_trend() -> None:
    close = pd.Series(
        np.concatenate([np.linspace(100, 160, 90), np.linspace(160, 100, 90)]),
        index=pd.bdate_range("2025-01-01", periods=180),
    )

    regime = market_regime(close, SignalParams())

    assert regime.iloc[85] == "up"
    assert regime.iloc[-1] == "down"
    assert set(regime.unique()) <= {"up", "down", "flat"}


# --- on the mock market ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def data(bt_engine: Any) -> Iterator[Dataset]:
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=bt_engine, expire_on_commit=False)() as session:
        yield load_dataset(session, UniverseOptions())


@pytest.fixture(scope="module")
def report(data: Dataset) -> dict[str, Any]:
    return run_signal_quality(data, SignalParams(), SignalQualityOptions(random_trials=5))


def test_every_event_is_filled_at_the_next_sessions_open(data: Dataset) -> None:
    """The lookahead test: a trade is done at the open after the signal, never at its own bar."""
    params = SignalParams()
    cands = screener_candidates(data, params)
    events = events_from(cands.selected, data)
    prices = open_prices(data)

    rows = event_table(
        data, cands, events, prices, 5, PandasEngine(), symmetric_fee(params), 0.001, limit=10_000
    )

    assert len(rows) > 5
    dates = list(data.dates.strftime("%Y-%m-%d"))
    real_open = data.panel["open"].to_numpy()
    close = data.panel["close"].to_numpy()
    for row in rows:
        t = dates.index(row["signal_date"])
        assert row["entry_date"] == dates[t + 1]  # the very next session
        assert row["exit_date"] == dates[t + 1 + 5]
        j = data.codes.index(row["code"])
        assert row["entry_price"] == real_open[t + 1, j]  # its open, not a close
        if np.isfinite(real_open[t + 6, j]):
            assert row["exit_price"] == real_open[t + 6, j]
        else:  # delisted while held: closed at the last price it had
            last = data.dates.get_loc(data.last_bar[row["code"]])
            assert row["exit_price"] == close[last, j]
        assert row["entry_price"] != close[t, j] or real_open[t + 1, j] == close[t, j]


def test_changing_the_fill_bar_changes_the_trade_but_not_the_signal(data: Dataset) -> None:
    params = SignalParams()
    cands = screener_candidates(data, params)
    events = events_from(cands.selected, data)
    prices = open_prices(data)
    engine = PandasEngine()
    paths, valid = event_paths(prices, events, 5)
    e = int(np.flatnonzero(valid)[0])
    t, j = int(events.day[e]), int(events.code[e])
    before = engine.trade_returns(paths[:, [e]], 0.0, 0.0)[0]

    changed = data.panel["open"].copy()
    values = changed.to_numpy().copy()
    values[t + 1, j] *= 1.5  # only the fill bar's open
    changed = pd.DataFrame(values, index=changed.index, columns=changed.columns)
    broken = Dataset(**{**data.__dict__, "panel": {**data.panel, "open": changed}})
    again = screener_candidates(broken, params)
    paths2, _ = event_paths(open_prices(broken), events, 5)
    after = engine.trade_returns(paths2[:, [e]], 0.0, 0.0)[0]

    day = data.dates[t]
    assert again.selected.loc[day, data.codes[j]]  # the pick of day t does not move
    assert paths2[0, e] == pytest.approx(1.5 * paths[0, e])  # but the buy price follows the open
    assert after == pytest.approx((1 + before) / 1.5 - 1)


def test_the_report_compares_the_scanner_with_the_three_baselines(report: dict[str, Any]) -> None:
    five = report["horizons"]["5"]

    assert set(five) == {"strategy", "universe", "random", "kospi"}
    assert five["strategy"]["n_events"] > 0
    assert five["universe"]["n_events"] > five["strategy"]["n_events"]
    assert "median" in five["strategy"] and "median" in five["random"]
    assert len(five["random"]["trial_medians"]) == 5
    assert report["primary_horizon"] == 5
    assert set(report["horizons"]) == {"1", "3", "5", "10", "20"}


def test_the_report_has_portfolio_ratios_regimes_costs_and_candidate_counts(
    report: dict[str, Any],
) -> None:
    ratios = report["portfolios"]
    assert set(ratios) >= {"strategy", "universe", "kospi", "random", "exposure"}
    assert set(ratios["strategy"]) == {
        "total_return", "annualized_return", "sharpe", "sortino", "calmar", "max_drawdown",
    }  # fmt: skip
    assert 0 < ratios["exposure"] <= 1
    assert set(report["regimes"]) == {"up", "down", "flat"}
    assert [row["slippage"] for row in report["slippage"]] == [0.0, 0.001, 0.003]
    assert report["slippage"][0]["mean"] >= report["slippage"][2]["mean"]  # slippage costs
    cands = report["candidates"]
    assert 0 <= cands["zero_days_share"] <= 1
    assert cands["per_day_mean"] >= 0
    assert cands["days"] == report["period"]["sessions"]


def test_the_curves_start_at_100_and_line_up(report: dict[str, Any]) -> None:
    curves = report["curves"]

    lengths = {len(v) for v in curves.values()}
    assert len(lengths) == 1
    assert curves["strategy"][0] == pytest.approx(100, rel=0.05)
    assert curves["dates"] == sorted(curves["dates"])


def test_too_few_signal_days_is_not_adoptable(data: Dataset) -> None:
    strict = run_signal_quality(
        data, SignalParams(), SignalQualityOptions(random_trials=1, min_sample_dates=10_000)
    )

    assert strict["adoption"]["adoptable"] is False
    assert "표본 부족" in strict["adoption"]["reasons"][0]


def test_the_same_seed_gives_the_same_report(data: Dataset) -> None:
    options = SignalQualityOptions(random_trials=3, seed=11, horizons=[5])
    first = run_signal_quality(data, SignalParams(), options)
    second = run_signal_quality(data, SignalParams(), options)

    assert first["horizons"] == second["horizons"]
    assert first["portfolios"] == second["portfolios"]


def test_quick_metrics_agree_with_the_full_report(data: Dataset, report: dict[str, Any]) -> None:
    quick = quick_metrics(data, SignalParams(), 5, 0.001)

    strategy = report["horizons"]["5"]["strategy"]
    assert quick["median_return"] == pytest.approx(strategy["median"])
    assert quick["n_dates"] == strategy["n_dates"]
    assert quick["candidates_per_day"] == pytest.approx(report["candidates"]["per_day_mean"])


def test_a_stricter_gate_leaves_fewer_candidates(data: Dataset) -> None:
    from app.backtest.config import with_param

    loose = quick_metrics(
        data, with_param(SignalParams(), "screener.drawdown_threshold_pct", -10), 5, 0.001
    )
    strict = quick_metrics(
        data, with_param(SignalParams(), "screener.drawdown_threshold_pct", -45), 5, 0.001
    )

    assert strict["candidates_per_day"] <= loose["candidates_per_day"]


@pytest.mark.skipif(
    not vectorbt_available(),
    reason="vectorbt is not installed on this platform (uv sync --extra backtest)",
)
def test_the_vectorbt_and_pandas_engines_give_the_same_report(data: Dataset) -> None:
    def run(engine: Any) -> dict[str, Any]:
        options = SignalQualityOptions(random_trials=3, seed=5, horizons=[3, 5], engine=engine)
        return run_signal_quality(data, SignalParams(), options)

    by_pandas, by_vectorbt = run("pandas"), run("vectorbt")

    assert (by_pandas["engine"], by_vectorbt["engine"]) == ("pandas", "vectorbt")
    for h in ("3", "5"):
        for key in ("strategy", "universe", "random", "kospi"):
            a, b = by_pandas["horizons"][h][key], by_vectorbt["horizons"][h][key]
            assert a["n_events"] == b["n_events"]
            for stat in ("mean", "median", "win_rate", "p10", "p90"):
                assert b[stat] == pytest.approx(a[stat], abs=1e-12), (h, key, stat)
    for name in ("strategy", "universe", "kospi"):
        for stat, value in by_pandas["portfolios"][name].items():
            assert by_vectorbt["portfolios"][name][stat] == pytest.approx(
                value, rel=1e-9, abs=1e-12
            )
    assert by_vectorbt["curves"] == pytest.approx(by_pandas["curves"])
