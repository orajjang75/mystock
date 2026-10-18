"""Signal quality of the screener (PRD 10장 백테스트 계획, 검증 기준).

Question: do the stocks the scanner picks do better over the following sessions than holding the
universe, picking at random, or holding the KOSPI?

Every candidate is an *event*: the scan of day t (made on t's confirmed close) is acted on at the
next bar's open (t+1), and the position is closed ``h`` sessions later at an open as well, so no
price that could not have been traded after the signal is ever used (룩어헤드 방지). Costs are
the fee and the sell tax of the settings, and a slippage on each side.

Round-trip returns and risk ratios come from a ``PortfolioEngine`` (vectorbt where installed).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.candidates import Candidates, screener_candidates
from app.backtest.config import SignalQualityOptions
from app.backtest.dataset import Dataset
from app.backtest.portfolio import PortfolioEngine, Ratios, get_engine
from app.engine.holding_rules import daily_downtrend
from app.engine.indicators import sma
from app.engine.params import SignalParams
from app.services.quantities import fee_rate_per_side

REGIMES = ("up", "down", "flat")


def symmetric_fee(params: SignalParams) -> float:
    """The fee paid on each side: the per-side commission plus half of the sell tax.

    A round trip costs the same as with the tax on the sell side only (to first order); folding
    it in lets vectorbt, which has one fee rate, and the pandas engine agree exactly.
    """
    return float(fee_rate_per_side(params.rebuy)) + params.rebuy.sell_tax_rate / 2


# --- events ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Events:
    """Signals as positions in the dataset's date axis and column list."""

    day: np.ndarray  # int: position of the signal day t
    code: np.ndarray  # int: position of the stock

    def __len__(self) -> int:
        return int(self.day.size)


@dataclass(frozen=True)
class Prices:
    """date x code opens plus where a position could really be entered."""

    opens: np.ndarray  # a delisted stock's later days held at its last close (the exit price)
    entry_ok: (
        np.ndarray
    )  # bool: the stock really traded that day, so a buy at its open was possible

    @classmethod
    def plain(cls, opens: np.ndarray) -> "Prices":
        return cls(opens, np.isfinite(opens))


def open_prices(data: Dataset) -> Prices:
    """The opens of the dataset.

    A position in a stock that vanished is closed at the last price it had, so a delisting is
    paid for instead of silently dropping the trade. But nothing can be *bought* after the last
    bar, so those days are not valid entries.
    """
    opens = data.panel["open"].to_numpy(dtype="float64").copy()
    entry_ok = np.isfinite(opens)
    closes = data.panel["close"]
    for code in data.delisted & set(data.codes):
        j = data.codes.index(code)
        last = data.dates.get_loc(data.last_bar[code])
        assert isinstance(last, int)
        opens[last + 1 :, j] = closes.iloc[last, j]
    return Prices(opens, entry_ok)


def events_from(mask: pd.DataFrame, data: Dataset) -> Events:
    rows, cols = np.nonzero(mask.to_numpy())
    offset = data.dates.get_loc(mask.index[0]) if len(mask.index) else 0
    assert isinstance(offset, int)
    return Events(day=rows + offset, code=cols)


def event_paths(
    prices: Prices | np.ndarray, events: Events, horizon: int
) -> tuple[np.ndarray, np.ndarray]:
    """(horizon + 1, n) prices from the entry open to the exit open, and which events have them.

    Entry is the open of the day *after* the signal; the exit ``horizon`` sessions later. An event
    whose exit lies beyond the data, or that has a missing price, is not valid.
    """
    if not isinstance(prices, Prices):
        prices = Prices.plain(prices)
    opens = prices.opens
    n_days = opens.shape[0]
    steps = np.arange(horizon + 1)[:, None]
    rows = events.day[None, :] + 1 + steps
    valid = rows[-1] <= n_days - 1
    rows = np.minimum(rows, n_days - 1)
    paths = opens[rows, events.code[None, :]]
    valid &= np.isfinite(paths).all(axis=0)
    valid &= prices.entry_ok[rows[0], events.code]
    return paths, valid


# --- statistics ------------------------------------------------------------------------------


def summarize(returns: np.ndarray, day: np.ndarray) -> dict[str, Any]:
    """Distribution of event returns, and the same read per signal day.

    Signals of the same day are not independent (the whole market moves), so the sample size
    that counts is ``n_dates`` and ``clustered_*`` average a day's events before looking at the
    spread across days.
    """
    returns = returns[np.isfinite(returns)] if returns.size else returns
    n = int(returns.size)
    if n == 0:
        return {"n_events": 0, "n_dates": 0}
    wins, losses = returns[returns > 0], returns[returns < 0]
    per_day = pd.Series(returns).groupby(day[: returns.size]).mean() if day.size >= n else None
    out: dict[str, Any] = {
        "n_events": n,
        "n_dates": int(np.unique(day).size) if day.size else 0,
        "mean": float(returns.mean()),
        "median": float(np.median(returns)),
        "std": float(returns.std(ddof=1)) if n > 1 else 0.0,
        "p10": float(np.percentile(returns, 10)),
        "p25": float(np.percentile(returns, 25)),
        "p75": float(np.percentile(returns, 75)),
        "p90": float(np.percentile(returns, 90)),
        "win_rate": float((returns > 0).mean()),
        "avg_win": float(wins.mean()) if wins.size else 0.0,
        "avg_loss": float(losses.mean()) if losses.size else 0.0,
        "payoff_ratio": float(wins.mean()) / abs(float(losses.mean()))
        if wins.size and losses.size
        else None,
        "profit_factor": float(wins.sum()) / abs(float(losses.sum())) if losses.size else None,
    }
    if per_day is not None and len(per_day):
        out["clustered_mean"] = float(per_day.mean())
        out["clustered_median"] = float(per_day.median())
    return out


def _trade_returns(
    engine: PortfolioEngine, paths: np.ndarray, valid: np.ndarray, fee: float, slippage: float
) -> np.ndarray:
    full = np.full(paths.shape[1], np.nan)
    if valid.any():
        full[valid] = engine.trade_returns(paths[:, valid], fee, slippage)
    return full


def market_regime(index_close: pd.Series, params: SignalParams) -> pd.Series:
    """KOSPI regime of each day: ``down`` (the A-6 definition applied to the index), ``up`` (the
    mirror image: above a rising moving average) or ``flat``. Backtest-only classification."""
    t = params.trend
    average = sma(index_close, t.ma_window)
    down = daily_downtrend(index_close, t.ma_window, t.slope_bars)
    up = (index_close > average) & (average > average.shift(t.slope_bars))
    regime = pd.Series("flat", index=index_close.index)
    regime[up] = "up"
    regime[down] = "down"
    return regime


# --- calendar-time portfolios ----------------------------------------------------------------


def daily_portfolio_returns(
    prices: Prices | np.ndarray,
    events: Events,
    horizon: int,
    net: np.ndarray,
    valid: np.ndarray,
    n_days: int,
) -> np.ndarray:
    """Daily returns of the equal-weight portfolio of the events that are open that day.

    Event e is held through the open-to-open intervals k = 0..horizon-1 after its entry; the
    portfolio's return of a day is the mean of those intervals, 0 on days with nothing held. The
    event's costs are put on its first interval, so compounding an event's intervals gives its
    net trade return.
    """
    sums = np.zeros(n_days)
    counts = np.zeros(n_days)
    paths, _ = event_paths(prices, events, horizon)
    day = events.day[valid]
    gross = paths[:, valid]
    ratio = gross[1:] / gross[:-1]  # (horizon, n)
    cost = (1 + net[valid]) / (gross[-1] / gross[0])
    ratio[0] = ratio[0] * cost
    for k in range(horizon):
        where = day + 1 + k  # the interval starts at the open of day t+1+k, which labels it
        sums += np.bincount(where, weights=ratio[k] - 1, minlength=n_days)[:n_days]
        counts += np.bincount(where, minlength=n_days)[:n_days]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)


def universe_daily_returns(opens: np.ndarray, members: np.ndarray) -> np.ndarray:
    """Open-to-open return of the equal-weight universe of each day (no costs: buy and hold)."""
    n_days = opens.shape[0]
    out = np.zeros(n_days)
    with np.errstate(invalid="ignore", divide="ignore"):
        step = opens[2:] / opens[1:-1] - 1
    ok = members[: n_days - 2] & np.isfinite(step)
    counts = ok.sum(axis=1)
    totals = np.where(ok, step, 0.0).sum(axis=1)
    out[1 : n_days - 1] = np.where(counts > 0, totals / np.maximum(counts, 1), 0.0)
    return out


def index_daily_returns(index_open: np.ndarray) -> np.ndarray:
    out = np.zeros(index_open.size)
    with np.errstate(invalid="ignore", divide="ignore"):
        step = index_open[2:] / index_open[1:-1] - 1
    out[1 : index_open.size - 1] = np.where(np.isfinite(step), step, 0.0)
    return out


# --- random entries --------------------------------------------------------------------------


def random_events(
    members: np.ndarray, per_day: np.ndarray, first: int, rng: np.random.Generator
) -> Events:
    """As many entries per day as the scanner had, drawn at random from that day's members."""
    n_days, n_codes = members.shape
    scores = np.where(members, rng.random((n_days, n_codes)), -1.0)
    order = np.argsort(-scores, axis=1)
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(n_codes)[None, :], axis=1)
    available = members.sum(axis=1)
    take = np.minimum(per_day, available)
    chosen = ranks < take[:, None]
    chosen &= members
    chosen[:first] = False
    rows, cols = np.nonzero(chosen)
    return Events(day=rows, code=cols)


# --- the run ---------------------------------------------------------------------------------


def _stats_for(
    engine: PortfolioEngine,
    prices: Prices,
    events: Events,
    horizon: int,
    fee: float,
    slippage: float,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    paths, valid = event_paths(prices, events, horizon)
    net = _trade_returns(engine, paths, valid, fee, slippage)
    return summarize(net[valid], events.day[valid]), net, valid


def candidate_stats(cands: Candidates) -> dict[str, Any]:
    n = cands.n_candidates
    return {
        "days": len(n),
        "per_day_mean": float(n.mean()) if len(n) else 0.0,
        "per_day_median": float(n.median()) if len(n) else 0.0,
        "zero_days": int((n == 0).sum()),
        "zero_days_share": float((n == 0).mean()) if len(n) else 0.0,
        "gate_modes": {str(k): int(v) for k, v in cands.gate_mode.value_counts().items() if k},
    }


def quick_metrics(
    data: Dataset,
    params: SignalParams,
    horizon: int,
    slippage: float,
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    engine: PortfolioEngine | None = None,
) -> dict[str, float]:
    """Just the strategy's numbers at one horizon, for sensitivity grids and walk-forward."""
    engine = engine or get_engine("pandas")
    start, end = window or (data.eval_start, data.eval_end)
    cands = screener_candidates(data, params, start, end)
    prices = open_prices(data)
    events = events_from(cands.selected, data)
    stats, _, _ = _stats_for(engine, prices, events, horizon, symmetric_fee(params), slippage)
    nan = float("nan")
    return {
        "median_return": stats.get("median", nan),
        "mean_return": stats.get("mean", nan),
        "win_rate": stats.get("win_rate", nan),
        "profit_factor": stats.get("profit_factor") or nan,
        "n_dates": float(stats.get("n_dates", 0)),
        "n_events": float(stats.get("n_events", 0)),
        "candidates_per_day": candidate_stats(cands)["per_day_mean"],
    }


def run_signal_quality(
    data: Dataset,
    params: SignalParams,
    options: SignalQualityOptions,
    *,
    cands: Candidates | None = None,
) -> dict[str, Any]:
    """The whole signal-quality report as JSON-friendly dicts."""
    engine = get_engine(options.engine)
    fee = symmetric_fee(params)
    cands = cands or screener_candidates(data, params)
    n_days = len(data.dates)
    first = data.dates.get_loc(cands.days[0]) if len(cands.days) else 0
    assert isinstance(first, int)
    prices = open_prices(data)
    members = data.members.to_numpy()
    events = events_from(cands.selected, data)
    slip = options.slippages[min(1, len(options.slippages) - 1)]  # the middle value is the base
    base_slip = 0.001 if 0.001 in options.slippages else slip
    rng = np.random.default_rng(options.seed)
    per_day = np.zeros(n_days, dtype=int)
    per_day[first : first + len(cands.n_candidates)] = cands.n_candidates.to_numpy()
    random_sets = [
        random_events(members, per_day, first, rng) for _ in range(options.random_trials)
    ]
    rows, cols = np.nonzero(members & (np.arange(n_days)[:, None] >= first))
    all_members = Events(day=rows, code=cols)
    index_open = data.index["open"].to_numpy(dtype="float64")

    horizons: dict[str, Any] = {}
    for h in options.horizons:
        strategy, _, _ = _stats_for(engine, prices, events, h, fee, base_slip)
        universe, _, _ = _stats_for(engine, prices, all_members, h, fee, base_slip)
        trials = [_stats_for(engine, prices, r, h, fee, base_slip) for r in random_sets]
        pooled = np.concatenate([t[1][t[2]] for t in trials]) if trials else np.array([])
        pooled_day = np.concatenate([random_sets[i].day[t[2]] for i, t in enumerate(trials)])
        random_stats = summarize(pooled, pooled_day)
        random_stats["trial_medians"] = [t[0].get("median") for t in trials if t[0].get("n_events")]
        # KOSPI over the same sessions: one path per signal day
        days = np.unique(events.day)
        idx_events = Events(day=days, code=np.zeros(days.size, dtype=int))
        idx_paths, idx_valid = event_paths(Prices.plain(index_open[:, None]), idx_events, h)
        idx_net = _trade_returns(engine, idx_paths, idx_valid, 0.0, 0.0)
        kospi = summarize(idx_net[idx_valid], days[idx_valid])
        horizons[str(h)] = {
            "strategy": strategy,
            "universe": universe,
            "random": random_stats,
            "kospi": kospi,
        }

    primary = options.primary_horizon
    ph = horizons[str(primary)]
    portfolios = _portfolios(
        engine, prices, events, random_sets, members, index_open, primary, fee, base_slip, first,
        n_days, data.dates,
    )  # fmt: skip

    regime = market_regime(data.index["close"].ffill(), params).reindex(data.dates)
    regimes = _by_regime(engine, prices, events, all_members, regime, primary, fee, base_slip)

    slippage_rows = []
    for s in options.slippages:
        mine, _, _ = _stats_for(engine, prices, events, primary, fee, s)
        base, _, _ = _stats_for(engine, prices, all_members, primary, fee, s)
        slippage_rows.append(
            {
                "slippage": s,
                "mean": mine.get("mean"),
                "median": mine.get("median"),
                "win_rate": mine.get("win_rate"),
                "universe_mean": base.get("mean"),
                "edge": (mine.get("mean") or 0.0) - (base.get("mean") or 0.0),
            }
        )

    n_dates = ph["strategy"].get("n_dates", 0)
    reasons = []
    if n_dates < options.min_sample_dates:
        reasons.append(f"신호가 난 날 {n_dates}일 < 최소 {options.min_sample_dates}일: 표본 부족")
    return {
        "engine": engine.name,
        "period": {
            "start": str(cands.days[0].date()) if len(cands.days) else None,
            "end": str(cands.days[-1].date()) if len(cands.days) else None,
            "sessions": len(cands.days),
        },
        "costs": {"fee_per_side": fee, "base_slippage": base_slip},
        "candidates": candidate_stats(cands),
        "primary_horizon": primary,
        "horizons": horizons,
        "portfolios": portfolios["ratios"],
        "curves": portfolios["curves"],
        "regimes": regimes,
        "slippage": slippage_rows,
        "adoption": {
            "adoptable": not reasons,
            "reasons": reasons,
            "min_sample_dates": options.min_sample_dates,
            "n_dates": n_dates,
        },
        "events": event_table(data, cands, events, prices, primary, engine, fee, base_slip),
    }


def _portfolios(
    engine: PortfolioEngine,
    prices: Prices,
    events: Events,
    random_sets: list[Events],
    members: np.ndarray,
    index_open: np.ndarray,
    horizon: int,
    fee: float,
    slippage: float,
    first: int,
    n_days: int,
    dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    window = slice(first, n_days)
    opens = prices.opens

    def series(ev: Events) -> np.ndarray:
        paths, valid = event_paths(prices, ev, horizon)
        net = _trade_returns(engine, paths, valid, fee, slippage)
        return daily_portfolio_returns(prices, ev, horizon, net, valid, n_days)

    def ratios(values: np.ndarray) -> Ratios:
        return engine.ratios(pd.Series(values[window]))

    strategy = series(events)
    universe = universe_daily_returns(opens, members)
    kospi = index_daily_returns(index_open)
    trial_series = [series(r) for r in random_sets]
    trial_ratios = [ratios(t) for t in trial_series]
    random_mean = {
        key: float(np.nanmean([getattr(r, key) for r in trial_ratios]))
        for key in Ratios.__dataclass_fields__
    }
    random_std = {
        key: float(np.nanstd([getattr(r, key) for r in trial_ratios]))
        for key in Ratios.__dataclass_fields__
    }
    held = np.zeros(n_days, dtype=bool)
    _, valid = event_paths(prices, events, horizon)
    for k in range(horizon):
        held[np.minimum(events.day[valid] + 1 + k, n_days - 1)] = True
    curves_idx = np.arange(first, n_days)
    step = max(1, len(curves_idx) // 300)
    picked = curves_idx[::step]

    def growth(values: np.ndarray) -> list[float]:
        curve = 100 * np.cumprod(1 + values[window])
        return [round(float(curve[i - first]), 4) for i in picked]

    random_mean_series = np.mean(trial_series, axis=0) if trial_series else np.zeros(n_days)
    return {
        "ratios": {
            "horizon": horizon,
            "exposure": float(held[window].mean()),
            "strategy": ratios(strategy).as_dict(),
            "universe": ratios(universe).as_dict(),
            "kospi": ratios(kospi).as_dict(),
            "random": {"mean": random_mean, "std": random_std, "trials": len(trial_ratios)},
        },
        "curves": {
            "dates": [str(dates[i].date()) for i in picked],
            "strategy": growth(strategy),
            "universe": growth(universe),
            "kospi": growth(kospi),
            "random": growth(random_mean_series),
        },
    }


def _by_regime(
    engine: PortfolioEngine,
    prices: Prices,
    events: Events,
    all_members: Events,
    regime: pd.Series,
    horizon: int,
    fee: float,
    slippage: float,
) -> dict[str, Any]:
    labels = regime.to_numpy()
    out: dict[str, Any] = {}
    s_paths, s_valid = event_paths(prices, events, horizon)
    s_net = _trade_returns(engine, s_paths, s_valid, fee, slippage)
    u_paths, u_valid = event_paths(prices, all_members, horizon)
    u_net = _trade_returns(engine, u_paths, u_valid, fee, slippage)
    for name in REGIMES:
        s_mask = s_valid & (labels[events.day] == name)
        u_mask = u_valid & (labels[all_members.day] == name)
        out[name] = {
            "strategy": summarize(s_net[s_mask], events.day[s_mask]),
            "universe": summarize(u_net[u_mask], all_members.day[u_mask]),
            "days": int((labels == name).sum()),
        }
    return out


def event_table(
    data: Dataset,
    cands: Candidates,
    events: Events,
    prices: Prices,
    horizon: int,
    engine: PortfolioEngine,
    fee: float,
    slippage: float,
    limit: int = 300,
) -> list[dict[str, Any]]:
    """The newest ``limit`` events: signal day, entry and exit price and day, net return."""
    paths, valid = event_paths(prices, events, horizon)
    net = _trade_returns(engine, paths, valid, fee, slippage)
    offset = data.dates.get_loc(cands.days[0])
    assert isinstance(offset, int)
    scores = cands.score.to_numpy()
    rows = []
    for e in np.flatnonzero(valid)[::-1][:limit]:
        t, j = int(events.day[e]), int(events.code[e])
        rows.append(
            {
                "signal_date": str(data.dates[t].date()),
                "code": data.codes[j],
                "name": data.names.get(data.codes[j], data.codes[j]),
                "score": float(scores[t - offset, j]),
                "entry_date": str(data.dates[t + 1].date()),
                "entry_price": float(paths[0, e]),
                "exit_date": str(data.dates[t + 1 + horizon].date()),
                "exit_price": float(paths[-1, e]),
                "return": float(net[e]),
            }
        )
    return rows
