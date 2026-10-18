import pytest
from fastapi.testclient import TestClient

from app.adapters.mock import MockAdapter, Scenario
from tests.conftest import END_DATE

DAY = END_DATE.isoformat()


def rebound_codes(adapter: MockAdapter, client: TestClient) -> set[str]:
    """Codes of the mock's rebound stocks that are in the saved universe."""
    watched = client.post("/api/screener/run").json()  # noqa: F841  (runs the scan once)
    items = client.get("/api/screener/results").json()["items"]
    return {item["code"] for item in items}


def test_every_new_endpoint_requires_a_login(client: TestClient) -> None:
    for method, path in [
        ("get", "/api/screener/results"),
        ("post", "/api/screener/run"),
        ("get", "/api/stocks/900010/candles"),
        ("get", "/api/stocks/900010/indicators"),
        ("get", "/api/watchlist"),
        ("post", "/api/watchlist"),
        ("delete", "/api/watchlist/900010"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_results_are_empty_before_the_first_scan(market_client: TestClient) -> None:
    body = market_client.get("/api/screener/results").json()

    assert body == {"scan_date": None, "scan_dates": [], "gate": None, "items": []}


def test_running_a_scan_saves_ranked_results(
    market_client: TestClient, mock_adapter: MockAdapter
) -> None:
    run = market_client.post("/api/screener/run")

    assert run.status_code == 200
    summary = run.json()
    assert summary["scan_date"] == DAY
    assert summary["universe_size"] == 120
    assert summary["gate_mode"] == "strict"
    assert summary["saved"] == summary["gated"] > 0
    assert summary["elapsed_seconds"] < 30

    body = market_client.get("/api/screener/results").json()
    assert body["scan_date"] == DAY
    assert body["scan_dates"] == [DAY]
    assert body["gate"] == {"mode": "strict", "drawdown_threshold_pct": -30.0}
    scores = [item["score"] for item in body["items"]]
    assert len(scores) == summary["saved"]
    assert scores == sorted(scores, reverse=True)


def test_only_bottom_then_rebound_stocks_are_listed(
    market_client: TestClient, mock_adapter: MockAdapter
) -> None:
    market_client.post("/api/screener/run")

    items = market_client.get("/api/screener/results").json()["items"]

    scenarios = {mock_adapter.stock(item["code"]).scenario for item in items}
    assert scenarios == {Scenario.REBOUND}
    top = items[0]
    assert top["tags"][0] == {"key": "drawdown", "label": "52주 낙폭"}
    assert {"name", "market", "close", "change_pct", "trading_value"} <= set(top)
    assert top["in_watchlist"] is False


def test_the_results_can_be_cut_by_score(market_client: TestClient) -> None:
    market_client.post("/api/screener/run")

    everything = market_client.get("/api/screener/results").json()["items"]
    cut = market_client.get("/api/screener/results", params={"min_score": 50}).json()["items"]

    assert 0 < len(cut) < len(everything)
    assert all(item["score"] >= 50 for item in cut)


def test_past_scan_results_can_be_viewed_by_date(market_client: TestClient) -> None:
    market_client.post("/api/screener/run", json={"scan_date": "2026-10-15"})
    market_client.post("/api/screener/run")

    latest = market_client.get("/api/screener/results").json()
    past = market_client.get("/api/screener/results", params={"scan_date": "2026-10-15"}).json()

    assert latest["scan_dates"] == [DAY, "2026-10-15"]
    assert past["scan_date"] == "2026-10-15"
    assert past["items"]
    assert (
        market_client.get("/api/screener/results", params={"scan_date": "2020-01-01"}).json()[
            "items"
        ]
        == []
    )


def test_a_scan_can_use_parameters_from_the_request(market_client: TestClient) -> None:
    default = market_client.post("/api/screener/run").json()
    from app.engine.params import SignalParams

    custom = SignalParams.model_validate({"scan": {"min_score": 50}}).model_dump(mode="json")

    cut = market_client.post("/api/screener/run", json={"params": custom}).json()

    assert cut["gated"] == default["gated"]
    assert 0 < cut["saved"] < default["saved"]


def test_a_non_trading_day_is_a_conflict(market_client: TestClient) -> None:
    response = market_client.post("/api/screener/run", json={"scan_date": "2026-10-17"})

    assert response.status_code == 409
    assert "No daily bars" in response.json()["detail"]


def test_an_invalid_parameter_is_rejected(market_client: TestClient) -> None:
    bad = {"params": {"score": {"flow_points": -5}}}

    assert market_client.post("/api/screener/run", json=bad).status_code == 422


# --- stocks -----------------------------------------------------------------------------------


def test_daily_candles_are_the_latest_bars_oldest_first(market_client: TestClient) -> None:
    response = market_client.get("/api/stocks/900010/candles", params={"limit": 5})

    candles = response.json()
    assert response.status_code == 200
    assert [c["time"] for c in candles] == [
        "2026-10-12",
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
    ]
    first = candles[0]
    assert first["low"] <= min(first["open"], first["close"])
    assert first["high"] >= max(first["open"], first["close"])
    assert isinstance(first["volume"], int)


def test_30_minute_candles_carry_kst_times(market_client: TestClient) -> None:
    candles = market_client.get(
        "/api/stocks/900010/candles", params={"bar": "30m", "limit": 13}
    ).json()

    assert len(candles) == 13
    assert candles[0]["time"] == "2026-10-16T09:00:00+09:00"
    assert candles[-1]["time"] == "2026-10-16T15:00:00+09:00"
    assert all(c["is_complete"] for c in candles)


def test_60_minute_candles_are_aggregated_with_a_30_minute_last_bar(
    market_client: TestClient,
) -> None:
    candles = market_client.get(
        "/api/stocks/900010/candles", params={"bar": "60m", "limit": 7}
    ).json()

    assert [c["time"][11:16] for c in candles] == [
        "09:00",
        "10:00",
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
    ]
    assert all(c["is_complete"] for c in candles)
    thirty = market_client.get(
        "/api/stocks/900010/candles", params={"bar": "30m", "limit": 2}
    ).json()
    assert candles[-1]["open"] == thirty[-1]["open"]  # the 15:00 hour is just the 15:00 bar
    assert candles[-1]["volume"] == thirty[-1]["volume"]


def test_unknown_stocks_and_bad_limits(market_client: TestClient) -> None:
    assert market_client.get("/api/stocks/NOPE/candles").status_code == 404
    assert market_client.get("/api/stocks/NOPE/indicators").status_code == 404
    assert market_client.get("/api/stocks/900010/candles", params={"limit": 0}).status_code == 422
    assert market_client.get("/api/stocks/900010/candles", params={"bar": "5m"}).status_code == 422


def test_indicators_cover_the_same_bars_as_the_candles(market_client: TestClient) -> None:
    candles = market_client.get("/api/stocks/900010/candles", params={"limit": 120}).json()

    body = market_client.get("/api/stocks/900010/indicators", params={"limit": 120}).json()

    assert body["code"] == "900010"
    assert body["bar"] == "1d"
    assert [p["time"] for p in body["points"]] == [c["time"] for c in candles]
    last = body["points"][-1]
    for name in ("rsi", "macd", "macd_signal", "macd_hist", "bb_lower", "bb_mid", "bb_upper"):
        assert last[name] is not None, name
    for name in ("pct_b", "bandwidth", "obv", "atr"):
        assert last[name] is not None, name
    assert last["bb_lower"] < last["bb_mid"] < last["bb_upper"]
    assert 0 <= last["rsi"] <= 100


def test_indicators_are_warmed_up_from_history_before_the_range(market_client: TestClient) -> None:
    first = market_client.get("/api/stocks/900010/indicators", params={"limit": 5}).json()[
        "points"
    ][0]

    assert first["macd_signal"] is not None  # needs 34 bars of history; only 5 were requested
    assert first["rsi"] is not None


def test_indicator_values_come_from_the_engine(market_client: TestClient) -> None:
    import pandas as pd

    from app.engine.indicators import rsi

    # the endpoint loads limit + 150 bars; the same 350 closes through the engine give the same RSI
    candles = market_client.get("/api/stocks/900010/candles", params={"limit": 350}).json()
    expected = rsi(pd.Series([c["close"] for c in candles]))
    points = market_client.get("/api/stocks/900010/indicators", params={"limit": 200}).json()[
        "points"
    ]

    assert abs(points[-1]["rsi"] - expected.iloc[-1]) < 1e-9


def test_indicators_include_daily_investor_flow(market_client: TestClient) -> None:
    body = market_client.get("/api/stocks/900010/indicators", params={"limit": 5}).json()

    assert [row["date"] for row in body["flow"]] == [p["time"] for p in body["points"]]
    assert set(body["flow"][0]) == {"date", "foreign_net_buy", "institution_net_buy"}


def test_intraday_indicators_return_valid_json_with_nulls_during_warm_up(
    market_client: TestClient,
) -> None:
    # all 60 days x 7 hourly bars: the first ones have no MACD signal yet (JSON null, not NaN)
    response = market_client.get(
        "/api/stocks/900010/indicators", params={"bar": "60m", "limit": 1000}
    )

    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 60 * 7
    assert points[0]["time"].endswith("+09:00")
    assert points[0]["macd_signal"] is None
    assert points[-1]["macd_signal"] is not None
    assert len(response.json()["flow"]) == 60  # daily flow of the covered days


def test_each_result_carries_the_evidence_and_score_breakdown(market_client: TestClient) -> None:
    market_client.post("/api/screener/run")

    top = market_client.get("/api/screener/results").json()["items"][0]

    evidence = top["evidence"]
    assert evidence["drawdown_pct"] <= -30
    for name in (
        "rsi",
        "pct_b",
        "disparity_pct",
        "volume_ratio",
        "net_buy_strength_pct",
        "macd_hist",
    ):
        assert name in evidence, name
    breakdown = evidence["breakdown"]
    assert set(breakdown) == {"reversal", "confirmation", "volume", "flow"}
    assert sum(breakdown.values()) == pytest.approx(
        top["score"] * evidence["max_points"] / 100, abs=0.01
    )
