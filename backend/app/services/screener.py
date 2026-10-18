"""Turnaround screener (PRD 4장 S-1~S-11, 6장 점수 표).

Pipeline: universe -> safety filter + 바닥 게이트 -> score (반전/확인/거래량/수급) -> save.
Every signal is computed by ``app.engine`` functions; this module only combines their results
into a gate, points and tags, so no formula lives here.
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Instrument, OhlcvDaily, ScanResult
from app.engine import screener_signals as sig
from app.engine.indicators import bollinger, macd, obv, rsi
from app.engine.params import ScoreParams, SignalParams
from app.services.bars import load_daily_panel
from app.services.settings import load_signal_params
from app.services.universe import load_universe

logger = logging.getLogger(__name__)

REVERSAL = ["rsi_cross_up", "bullish_divergence", "bollinger_reentry"]
CONFIRMATION = [
    "macd_golden_cross",
    "close_above_ma20",
    "ma5_above_ma20",
    "downwave_breakout",
    "obv_turn_up",
]
FLOW = ["foreign_consecutive", "institution_consecutive", "net_buy_strength", "net_buy_turnaround"]

TAG_LABELS = {
    "drawdown": "52주 낙폭",
    "disparity": "이격도 과매도",
    "bollinger_break": "볼린저 하단 이탈 이력",
    "rsi_cross_up": "RSI 30 상향 돌파",
    "bullish_divergence": "강세 다이버전스",
    "bollinger_reentry": "볼린저 복귀",
    "macd_golden_cross": "MACD 골든크로스",
    "close_above_ma20": "종가 20일선 회복",
    "ma5_above_ma20": "5일선 > 20일선",
    "downwave_breakout": "하락 파동 고점 돌파",
    "obv_turn_up": "OBV 상승 전환",
    "volume_2x": "거래량 2배",
    "volume_3x": "거래량 3배",
    "foreign_consecutive": "외국인 연속 순매수",
    "institution_consecutive": "기관 연속 순매수",
    "net_buy_strength": "순매수 강도",
    "net_buy_turnaround": "순매수 전환",
    "flow_unreflected": "수급 미반영",
}


class ScanError(RuntimeError):
    """The scan cannot run (no universe, no data for the date)."""


@dataclass(frozen=True, slots=True)
class ScanSummary:
    scan_date: date
    universe_size: int
    gate_mode: str  # strict | relaxed | decline_rank
    drawdown_threshold_pct: float | None
    gated: int  # stocks that passed the gate
    saved: int  # stocks saved after the minimum-score cut
    elapsed_seconds: float


# --- signals ---------------------------------------------------------------------------------


def compute_signal_table(panel: dict[str, pd.DataFrame], params: SignalParams) -> dict[str, Any]:
    """All screener signals and evidence values as wide frames (date x code)."""
    ind, s = params.indicators, params.screener
    o, h, low, c = (panel[k] for k in ("open", "high", "low", "close"))
    v, tv = panel["volume"], panel["trading_value"]
    foreign, institution = panel["foreign_net_buy"], panel["institution_net_buy"]

    rsi_value = rsi(c, ind.rsi_period)
    bands = bollinger(c, ind.bollinger_window, ind.bollinger_k)
    pct_b = pd.DataFrame(bands["pct_b"])
    macd_frame = macd(c, ind.macd_fast, ind.macd_slow, ind.macd_signal)
    macd_line, macd_signal = pd.DataFrame(macd_frame["macd"]), pd.DataFrame(macd_frame["signal"])
    obv_value = obv(c, v)

    return {
        "liquidity": sig.liquidity_ok(tv, s.min_avg_trading_value, s.liquidity_window),
        "drawdown_pct": sig.drawdown_52w_pct(h, c, s.drawdown_window),
        "disparity_pct": sig.disparity_pct(c, s.disparity_window),
        "disparity": sig.disparity_oversold(c, s.disparity_threshold_pct, s.disparity_window),
        "bollinger_break": sig.bollinger_break_history(pct_b, s.bollinger_break_lookback),
        "rsi_cross_up": sig.rsi_cross_up(rsi_value, s.rsi_cross_level),
        "bullish_divergence": sig.bullish_divergence(
            low, rsi_value, s.swing_confirm_bars, s.divergence_lookback
        ),
        "bollinger_reentry": sig.bollinger_reentry(pct_b),
        "macd_golden_cross": sig.macd_golden_cross(
            macd_line, macd_signal, s.macd_cross_below_zero_only
        ),
        "close_above_ma20": sig.close_above_ma(c, s.ma_long_window),
        "ma5_above_ma20": sig.ma_short_above_long(c, s.ma_short_window, s.ma_long_window),
        "downwave_breakout": sig.downwave_high_breakout(c, h, s.swing_confirm_bars),
        "obv_turn_up": sig.obv_turn_up(obv_value, s.obv_ma_window),
        "volume_2x": sig.volume_surge(v, o, c, s.volume_multiple, s.volume_window),
        "volume_3x": sig.volume_surge(v, o, c, s.volume_strong_multiple, s.volume_window),
        "foreign_consecutive": sig.consecutive_net_buy(foreign, s.flow_consecutive_days),
        "institution_consecutive": sig.consecutive_net_buy(institution, s.flow_consecutive_days),
        "net_buy_strength": sig.net_buy_strength(
            foreign, institution, tv, s.flow_strength_threshold_pct, s.flow_strength_window
        ),
        "net_buy_turnaround": sig.net_buy_turnaround(
            foreign, institution, s.flow_turnaround_window
        ),
        "flow_unreflected": sig.flow_missing(
            foreign,
            institution,
            max(s.flow_consecutive_days, s.flow_strength_window, 2 * s.flow_turnaround_window),
        ),
        # evidence values
        "rsi": rsi_value,
        "pct_b": pct_b,
        "macd_hist": pd.DataFrame(macd_frame["hist"]),
        "volume_ratio": sig.volume_ratio(v, s.volume_window),
        "net_buy_strength_pct": sig.net_buy_strength_pct(
            foreign, institution, tv, s.flow_strength_window
        ),
        "avg_trading_value": sig.avg_trading_value(tv, s.liquidity_window),
        "close": c,
        "change_pct": c.pct_change() * 100,
        "trading_value": tv,
    }


def signals_on(table: dict[str, Any], day: pd.Timestamp) -> pd.DataFrame:
    """One row per stock: the signal table cut at ``day``."""
    return pd.DataFrame({name: frame.loc[day] for name, frame in table.items()})


# --- gate ------------------------------------------------------------------------------------


def apply_gate(
    row: pd.DataFrame, params: SignalParams, drawdown_threshold_pct: float | None = None
) -> pd.Series:
    """S-2: 안전 필터 AND 52주 낙폭 AND (이격도 OR 볼린저 하단 이탈 이력).

    The drawdown test is re-evaluated against ``drawdown_threshold_pct`` (default: the
    configured threshold) so the relaxed option can reuse the same signals.
    """
    threshold = (
        params.screener.drawdown_threshold_pct
        if drawdown_threshold_pct is None
        else drawdown_threshold_pct
    )
    drawdown = row["drawdown_pct"].round(8) <= threshold
    liquid = row["liquidity"].astype(bool)
    return liquid & drawdown & (row["disparity"].astype(bool) | row["bollinger_break"].astype(bool))


def select_candidates(
    row: pd.DataFrame, params: SignalParams
) -> tuple[pd.Series, str, float | None]:
    """The gate result plus how it was reached: (mask, mode, drawdown threshold used).

    If fewer than ``few_candidates_threshold`` stocks pass and an action is configured, the
    drawdown threshold is relaxed, or the stocks with the deepest 52-week drawdown are taken.
    """
    scan, strict = params.scan, params.screener.drawdown_threshold_pct
    gate = apply_gate(row, params)
    if gate.sum() >= scan.few_candidates_threshold or scan.few_candidates_action == "none":
        return gate, "strict", strict
    if scan.few_candidates_action == "relax_drawdown":
        relaxed = params.screener.drawdown_relaxed_threshold_pct
        return apply_gate(row, params, relaxed), "relaxed", relaxed
    liquid = row["liquidity"].astype(bool) & row["drawdown_pct"].notna()
    deepest = row["drawdown_pct"].where(liquid).nsmallest(scan.decline_rank_top_n).index
    return pd.Series(row.index.isin(deepest), index=row.index), "decline_rank", None


# --- score -----------------------------------------------------------------------------------


def score_rows(row: pd.DataFrame, weights: ScoreParams) -> pd.DataFrame:
    """Points per section and the 0-100 total for each stock.

    Columns: ``reversal``, ``confirmation``, ``volume``, ``flow`` (earned points), ``max_points``
    (the weights that applied) and ``score``. Without flow data (``flow_unreflected``) the flow
    section is dropped from both, which rescales the rest to 100.
    """
    flags = row.astype(dict.fromkeys([*REVERSAL, *CONFIRMATION, *FLOW], bool))
    unreflected = row["flow_unreflected"].astype(bool)

    reversal = flags[REVERSAL].sum(axis=1) * weights.reversal_points / len(REVERSAL)
    confirmation = flags[CONFIRMATION].sum(axis=1) * weights.confirmation_points / len(CONFIRMATION)
    two_x_share = weights.volume_multiple_points / weights.volume_strong_multiple_points
    volume_share = np.where(
        row["volume_3x"].astype(bool),
        1.0,
        np.where(row["volume_2x"].astype(bool), two_x_share, 0.0),
    )
    volume = pd.Series(weights.volume_points * volume_share, index=row.index)
    flow = (flags[FLOW].sum(axis=1) * weights.flow_points / len(FLOW)).where(~unreflected, 0.0)

    max_points = (
        weights.reversal_points
        + weights.confirmation_points
        + weights.volume_points
        + weights.flow_points * (~unreflected)
    )
    earned = reversal + confirmation + volume + flow
    score = (100 * earned / max_points.where(max_points > 0)).fillna(0.0).round(2)
    return pd.DataFrame(
        {
            "reversal": reversal,
            "confirmation": confirmation,
            "volume": volume,
            "flow": flow,
            "max_points": max_points,
            "score": score,
        }
    )


def tags_for(row: pd.Series) -> list[str]:
    """Condition tag keys met by one stock, in display order."""
    keys = ["drawdown", "disparity", "bollinger_break", *REVERSAL, *CONFIRMATION]
    met = [key for key in keys if _tag_met(row, key)]
    met += ["volume_3x"] if row["volume_3x"] else ["volume_2x"] if row["volume_2x"] else []
    met += [key for key in FLOW if row[key]]
    return [*met, "flow_unreflected"] if row["flow_unreflected"] else met


def _tag_met(row: pd.Series, key: str) -> bool:
    if key == "drawdown":
        return bool(row["drawdown_met"])
    return bool(row[key])


def evaluate_row(
    row: pd.DataFrame, params: SignalParams
) -> tuple[pd.DataFrame, str, float | None, int]:
    """One day's scan: gate, score, minimum-score cut.

    Returns the kept stocks (signals plus points), the gate mode and threshold used, and how many
    passed the gate. The daily scan and the backtest both call this, so a backtest selects
    candidates exactly as the scanner would have on that day.
    """
    mask, mode, threshold = select_candidates(row, params)
    candidates = row[mask].copy()
    # In decline_rank mode no threshold was applied; the tag still reports the configured one.
    tag_threshold = params.screener.drawdown_threshold_pct if threshold is None else threshold
    candidates["drawdown_met"] = candidates["drawdown_pct"].round(8) <= tag_threshold
    points = score_rows(candidates, params.score)
    candidates = candidates.join(points)
    kept = candidates[candidates["score"] >= params.scan.min_score]
    return kept, mode, threshold, len(candidates)


# --- evidence and persistence ----------------------------------------------------------------


def _plain(value: Any) -> Any:
    """JSON-safe scalar: numpy -> python, NaN/inf -> None."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


EVIDENCE_COLUMNS = [
    "close",
    "change_pct",
    "trading_value",
    "avg_trading_value",
    "drawdown_pct",
    "disparity_pct",
    "pct_b",
    "rsi",
    "macd_hist",
    "volume_ratio",
    "net_buy_strength_pct",
]


def _universe_codes(session: Session) -> list[str]:
    members = load_universe(session)
    if not members:
        raise ScanError("The scan universe is empty; run the ingest job first.")
    return [member.code for member in members]


def latest_bar_date(session: Session) -> date | None:
    return session.scalar(select(func.max(OhlcvDaily.trade_date)))


def run_scan(
    session: Session, scan_date: date | None = None, params: SignalParams | None = None
) -> ScanSummary:
    """Scan the stored universe for ``scan_date`` (default: the latest bar date) and save it.

    ``params`` default to the saved settings. Re-running a date replaces its saved results.
    Flushes but does not commit.
    """
    started = time.monotonic()
    params = params or load_signal_params(session)
    codes = _universe_codes(session)
    scan_date = scan_date or latest_bar_date(session)
    if scan_date is None:
        raise ScanError("No daily bars are stored; run the ingest job first.")

    panel = load_daily_panel(session, codes, scan_date)
    day = pd.Timestamp(scan_date)
    if day not in panel["close"].index:
        raise ScanError(f"No daily bars for {scan_date}; is it a trading day?")
    row = signals_on(compute_signal_table(panel, params), day)

    kept, mode, threshold, gated = evaluate_row(row, params)

    _save(session, scan_date, kept, params, mode, threshold)
    summary = ScanSummary(
        scan_date=scan_date,
        universe_size=len(codes),
        gate_mode=mode,
        drawdown_threshold_pct=threshold,
        gated=gated,
        saved=len(kept),
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    logger.info("scan finished in %.2fs: %s", summary.elapsed_seconds, summary)
    return summary


def _save(
    session: Session,
    scan_date: date,
    kept: pd.DataFrame,
    params: SignalParams,
    mode: str,
    threshold: float | None,
) -> None:
    used = {
        "signal_params": params.model_dump(mode="json"),
        "gate": {"mode": mode, "drawdown_threshold_pct": threshold},
    }
    session.execute(delete(ScanResult).where(ScanResult.scan_date == scan_date))
    ordered = kept.sort_values(["score"], ascending=False, kind="stable")
    for code, item in ordered.iterrows():
        evidence = {name: _plain(item[name]) for name in EVIDENCE_COLUMNS}
        evidence["breakdown"] = {
            name: _plain(item[name]) for name in ("reversal", "confirmation", "volume", "flow")
        }
        evidence["max_points"] = _plain(item["max_points"])
        session.add(
            ScanResult(
                scan_date=scan_date,
                code=str(code),
                score=round(float(item["score"]), 2),
                tags=tags_for(item),
                indicators=evidence,
                params=used,
            )
        )
    session.flush()


# --- reading results -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultRow:
    code: str
    name: str
    market: str
    score: float
    tags: list[str]
    close: float | None
    change_pct: float | None
    trading_value: float | None
    flow_unreflected: bool
    evidence: dict[str, Any]


def scan_dates(session: Session, limit: int = 120) -> list[date]:
    """Dates with saved results, newest first."""
    return list(
        session.scalars(
            select(ScanResult.scan_date)
            .distinct()
            .order_by(ScanResult.scan_date.desc())
            .limit(limit)
        )
    )


def results_for(session: Session, scan_date: date, min_score: float = 0.0) -> list[ResultRow]:
    """Saved results of one date, highest score first."""
    rows = session.execute(
        select(ScanResult, Instrument)
        .join(Instrument, Instrument.code == ScanResult.code)
        .where(ScanResult.scan_date == scan_date, ScanResult.score >= min_score)
        .order_by(ScanResult.score.desc(), ScanResult.code)
    ).all()
    return [
        ResultRow(
            code=result.code,
            name=instrument.name,
            market=instrument.market.value,
            score=float(result.score),
            tags=list(result.tags),
            close=result.indicators.get("close"),
            change_pct=result.indicators.get("change_pct"),
            trading_value=result.indicators.get("trading_value"),
            flow_unreflected="flow_unreflected" in result.tags,
            evidence=dict(result.indicators),
        )
        for result, instrument in rows
    ]
