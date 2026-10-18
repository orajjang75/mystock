"""The screener on the full mock market: 120 stocks, 24 of them 'bottom then rebound'."""

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.mock import MockAdapter, Scenario
from app.db.models import InvestorFlowDaily, ScanResult
from app.engine.params import SignalParams
from app.jobs.ingest import run_ingest
from app.services.bars import load_daily_panel
from app.services.screener import ScanError, results_for, run_scan, scan_dates
from app.services.settings import load_signal_params, save_signal_params
from app.services.universe import UniverseSpec, load_universe
from tests.conftest import AFTER_CLOSE, END_DATE, sqlite_engine


def members_with(adapter: MockAdapter, session: Session, *scenarios: Scenario) -> set[str]:
    return {m.code for m in load_universe(session) if adapter.stock(m.code).scenario in scenarios}


def test_the_scan_saves_ranked_results(market: Session, mock_adapter: MockAdapter) -> None:
    summary = run_scan(market)
    market.commit()

    assert summary.scan_date == END_DATE
    assert summary.universe_size == 120
    assert summary.gate_mode == "strict"
    assert summary.gated == summary.saved > 0
    results = results_for(market, END_DATE)
    assert len(results) == summary.saved
    scores = [row.score for row in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 100 for score in scores)


def test_bottom_then_rebound_stocks_make_the_list_and_the_others_fail_the_gate(
    market: Session, mock_adapter: MockAdapter
) -> None:
    run_scan(market)
    market.commit()

    found = {row.code for row in results_for(market, END_DATE)}
    rebounds = members_with(mock_adapter, market, Scenario.REBOUND)
    others = members_with(
        mock_adapter, market, Scenario.DOWNTREND, Scenario.SIDEWAYS, Scenario.UPTREND
    )

    assert len(rebounds) >= 20
    assert found == rebounds  # every rebound stock passes the gate, nothing else does
    assert not found & others  # 계속 하락 (and sideways, uptrend) are dropped at the gate


def test_rebound_stocks_score_well_above_zero(market: Session) -> None:
    run_scan(market)

    results = results_for(market, END_DATE)

    assert min(row.score for row in results) >= 40  # volume + flow + the 20-day line recovery
    assert all("drawdown" in row.tags for row in results)
    assert all(not row.flow_unreflected for row in results)


def test_a_120_stock_scan_is_far_faster_than_ten_minutes(market: Session) -> None:
    summary = run_scan(market)

    assert summary.elapsed_seconds < 30  # the PRD target is 600


def test_results_keep_tags_evidence_and_the_parameters_that_produced_them(
    market: Session,
) -> None:
    run_scan(market)
    market.commit()

    row = market.scalars(
        select(ScanResult).where(ScanResult.scan_date == END_DATE).order_by(ScanResult.score.desc())
    ).first()

    assert row is not None
    assert "drawdown" in row.tags
    assert row.indicators["drawdown_pct"] <= -30
    assert {"close", "change_pct", "trading_value", "rsi", "pct_b", "volume_ratio"} <= set(
        row.indicators
    )
    breakdown = row.indicators["breakdown"]
    assert breakdown["reversal"] + breakdown["confirmation"] + breakdown["volume"] + breakdown[
        "flow"
    ] == pytest.approx(float(row.score))
    assert row.params["gate"] == {"mode": "strict", "drawdown_threshold_pct": -30.0}
    assert row.params["signal_params"]["screener"]["drawdown_threshold_pct"] == -30.0


def test_the_saved_parameters_are_enough_to_reproduce_the_scan(market: Session) -> None:
    run_scan(market)
    market.commit()
    first = {(r.code, r.score) for r in results_for(market, END_DATE)}
    stored = market.scalars(select(ScanResult.params).limit(1)).one()

    run_scan(market, END_DATE, SignalParams.model_validate(stored["signal_params"]))

    assert {(r.code, r.score) for r in results_for(market, END_DATE)} == first


def test_rescanning_a_date_replaces_its_results(market: Session) -> None:
    run_scan(market)
    market.commit()
    before = market.scalar(select(func.count()).select_from(ScanResult))

    run_scan(market)
    market.commit()

    assert market.scalar(select(func.count()).select_from(ScanResult)) == before


def test_each_scan_date_is_stored_separately(market: Session) -> None:
    run_scan(market, END_DATE - timedelta(days=1))
    run_scan(market, END_DATE)
    market.commit()

    assert scan_dates(market) == [END_DATE, END_DATE - timedelta(days=1)]
    assert results_for(market, END_DATE - timedelta(days=1))


def test_a_scan_only_sees_bars_up_to_its_date(market: Session) -> None:
    codes = [m.code for m in load_universe(market)]
    cutoff = END_DATE - timedelta(days=30)

    panel = load_daily_panel(market, codes, cutoff)

    assert panel["close"].index.max() <= pd.Timestamp(cutoff)


def test_a_minimum_score_cut_drops_low_scores_but_not_the_gate_count(market: Session) -> None:
    params = SignalParams.model_validate({"scan": {"min_score": 50}})

    summary = run_scan(market, params=params)

    results = results_for(market, END_DATE)
    assert summary.saved < summary.gated
    assert results
    assert all(row.score >= 50 for row in results)


def test_weights_from_the_settings_change_the_scores(market: Session) -> None:
    run_scan(market)
    default_scores = {r.code: r.score for r in results_for(market, END_DATE)}

    heavy = SignalParams.model_validate({"score": {"flow_points": 0}})
    run_scan(market, params=heavy)
    new_scores = {r.code: r.score for r in results_for(market, END_DATE)}

    # every rebound stock earns the full flow section (20) of its default score, so without
    # it the rest is rescaled to the remaining 80 points
    for code, old in default_scores.items():
        assert new_scores[code] == pytest.approx(100 * (old - 20) / 80, abs=0.01)


def test_saved_settings_are_used_when_no_parameters_are_given(market: Session) -> None:
    save_signal_params(market, SignalParams.model_validate({"scan": {"min_score": 55}}))
    market.commit()

    run_scan(market)

    assert all(row.score >= 55 for row in results_for(market, END_DATE))
    assert load_signal_params(market).scan.min_score == 55


def test_relaxing_the_drawdown_when_candidates_are_few(market: Session) -> None:
    strict = run_scan(market)
    params = SignalParams.model_validate(
        {"scan": {"few_candidates_action": "relax_drawdown", "few_candidates_threshold": 1000}}
    )

    relaxed = run_scan(market, params=params)

    assert (relaxed.gate_mode, relaxed.drawdown_threshold_pct) == ("relaxed", -20.0)
    assert relaxed.gated >= strict.gated


def test_ranking_by_decline_when_candidates_are_few(market: Session) -> None:
    params = SignalParams.model_validate(
        {
            "scan": {
                "few_candidates_action": "rank_by_decline",
                "few_candidates_threshold": 1000,
                "decline_rank_top_n": 15,
            }
        }
    )

    summary = run_scan(market, params=params)

    assert (summary.gate_mode, summary.gated) == ("decline_rank", 15)
    stored = market.scalars(select(ScanResult.params).limit(1)).one()
    assert stored["gate"]["mode"] == "decline_rank"


def test_without_flow_data_the_score_is_rescaled_and_tagged() -> None:
    adapter = MockAdapter(seed=7, end_date=END_DATE, n_kospi=30, n_kosdaq=10)
    engine = sqlite_engine()
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        run_ingest(
            db,
            adapter,
            as_of=END_DATE,
            now=AFTER_CLOSE,
            spec=UniverseSpec(kospi_top=20, kosdaq_top=5),
        )
        run_scan(db)
        before = {r.code: r for r in results_for(db, END_DATE)}
        code = next(iter(before))
        assert before[code].score > 20  # flow section fully earned: see the mock's rebound flows

        db.execute(
            delete(InvestorFlowDaily).where(
                InvestorFlowDaily.code == code,
                InvestorFlowDaily.trade_date >= END_DATE - timedelta(days=3),
            )
        )
        run_scan(db)
        after = {r.code: r for r in results_for(db, END_DATE)}

    assert after[code].flow_unreflected
    assert "flow_unreflected" in after[code].tags
    assert after[code].score == pytest.approx(100 * (before[code].score - 20) / 80, abs=0.01)
    others = [c for c in before if c != code]
    assert all(not after[c].flow_unreflected for c in others)


def test_scanning_an_empty_database_explains_what_is_missing() -> None:
    with sessionmaker(bind=sqlite_engine())() as db, pytest.raises(ScanError, match="universe"):
        run_scan(db)


def test_a_date_without_bars_is_refused(market: Session) -> None:
    with pytest.raises(ScanError, match="No daily bars for"):
        run_scan(market, date(2026, 10, 17))  # a Saturday
