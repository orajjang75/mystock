import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.adapters.mock import MockAdapter, Scenario
from app.services.screener import results_for
from tests.conftest import END_DATE


@pytest.fixture
def code(market_client: TestClient) -> str:
    """A stock that is in the scan universe and passes the gate."""
    market_client.post("/api/screener/run")
    return str(market_client.get("/api/screener/results").json()["items"][0]["code"])


def test_a_universe_stock_can_be_added_once(market_client: TestClient, code: str) -> None:
    first = market_client.post("/api/watchlist", json={"code": code})
    again = market_client.post("/api/watchlist", json={"code": code})

    assert first.status_code == 201
    assert again.status_code == 200
    assert [item["code"] for item in market_client.get("/api/watchlist").json()] == [code]


def test_stocks_outside_the_scan_universe_cannot_be_added(
    market_client: TestClient, mock_adapter: MockAdapter
) -> None:
    excluded = next(s.code for s in mock_adapter.stocks if s.is_admin_issue)

    response = market_client.post("/api/watchlist", json={"code": excluded})

    assert response.status_code == 422
    assert "scan universe" in response.json()["detail"]
    assert market_client.post("/api/watchlist", json={"code": "NOPE"}).status_code == 422
    assert market_client.get("/api/watchlist").json() == []


def test_the_list_shows_the_latest_score_and_the_change_since_the_previous_scan(
    market_client: TestClient, code: str
) -> None:
    market_client.post("/api/screener/run", json={"scan_date": "2026-10-15"})
    market_client.post("/api/screener/run")
    market_client.post("/api/watchlist", json={"code": code})

    item = market_client.get("/api/watchlist").json()[0]

    assert item["code"] == code
    assert item["scan_date"] == END_DATE.isoformat()
    assert item["previous_scan_date"] == "2026-10-15"
    assert item["score"] is not None
    assert item["previous_score"] is not None
    assert item["change"] == pytest.approx(item["score"] - item["previous_score"], abs=0.01)
    assert item["name"]


def test_without_an_earlier_scan_there_is_no_change(market_client: TestClient, code: str) -> None:
    market_client.post("/api/watchlist", json={"code": code})

    item = market_client.get("/api/watchlist").json()[0]

    assert item["score"] is not None
    assert (item["previous_score"], item["previous_scan_date"], item["change"]) == (
        None,
        None,
        None,
    )


def test_a_stock_that_failed_the_gate_has_no_score_but_stays_on_the_list(
    market_client: TestClient, mock_adapter: MockAdapter, code: str
) -> None:
    sideways = next(
        s.code
        for s in mock_adapter.stocks
        if s.scenario is Scenario.SIDEWAYS
        and not (s.is_admin_issue or s.is_halted or s.is_warning or s.is_preferred or s.is_illiquid)
        and s.position < 90
    )
    market_client.post("/api/watchlist", json={"code": sideways})
    market_client.post("/api/watchlist", json={"code": code})

    items = market_client.get("/api/watchlist").json()

    assert [i["code"] for i in items] == [code, sideways]  # scored stocks first
    assert items[1]["score"] is None
    assert items[1]["change"] is None


def test_removing_a_stock(market_client: TestClient, code: str) -> None:
    market_client.post("/api/watchlist", json={"code": code})

    assert market_client.delete(f"/api/watchlist/{code}").status_code == 204
    assert market_client.get("/api/watchlist").json() == []
    assert market_client.delete(f"/api/watchlist/{code}").status_code == 404


def test_results_mark_watched_stocks(market_client: TestClient, code: str) -> None:
    market_client.post("/api/watchlist", json={"code": code})

    items = market_client.get("/api/screener/results").json()["items"]

    assert {i["code"]: i["in_watchlist"] for i in items}[code] is True
    assert sum(i["in_watchlist"] for i in items) == 1


def test_the_score_in_the_list_matches_the_saved_result(
    market_client: TestClient, market_engine: Engine, code: str
) -> None:

    market_client.post("/api/watchlist", json={"code": code})
    shown = market_client.get("/api/watchlist").json()[0]["score"]

    with sessionmaker(bind=market_engine)() as db:
        saved = next(r.score for r in results_for(db, END_DATE) if r.code == code)

    assert shown == saved
