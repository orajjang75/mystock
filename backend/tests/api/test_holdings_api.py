from typing import Any

import pytest
from fastapi.testclient import TestClient

CODE = "900010"


def use_hand_rates(client: TestClient) -> None:
    """The expected numbers below are worked out by hand with fixed rates (0.03% / 0.18%)."""
    settings = client.get("/api/settings").json()
    settings["signal_params"]["rebuy"].update(round_trip_fee_rate=0.0003, sell_tax_rate=0.0018)
    assert client.put("/api/settings", json=settings).status_code == 200


def create(client: TestClient, quantity: int = 100, avg_price: int = 90_000) -> dict[str, Any]:
    response = client.post(
        "/api/holdings", json={"code": CODE, "quantity": quantity, "avg_price": avg_price}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def fill(
    client: TestClient, holding_id: int, side: str, price: int, quantity: int, **extra: Any
) -> Any:
    body = {"side": side, "price": price, "quantity": quantity, **extra}
    return client.post(f"/api/holdings/{holding_id}/fills", json=body)


def test_every_holdings_endpoint_requires_a_login(client: TestClient) -> None:
    for method, path in [
        ("get", "/api/holdings"),
        ("post", "/api/holdings"),
        ("put", "/api/holdings/1"),
        ("delete", "/api/holdings/1"),
        ("post", "/api/holdings/1/fills"),
        ("get", "/api/holdings/1/cycles"),
        ("post", "/api/holdings/1/cycles/1/retry"),
        ("post", "/api/holdings/1/cycles/1/abandon"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_registering_a_holding_records_the_start_quantity(market_client: TestClient) -> None:
    holding = create(market_client, 100, 90_000)

    assert holding["code"] == CODE
    assert holding["name"]
    assert (holding["quantity"], holding["start_quantity"]) == (100, 100)
    assert holding["state"] == "holding"
    assert holding["open_cycle"] is None
    assert holding["cumulative_increase"] == 0


def test_the_list_shows_the_price_trend_and_atr_stop(market_client: TestClient) -> None:
    create(market_client)

    (item,) = market_client.get("/api/holdings").json()

    assert item["last_close"] > 0
    assert isinstance(item["daily_downtrend"], bool)
    assert item["stop_price"] is not None
    assert item["stop_price"] < item["avg_price"]  # average cost minus two ATR


@pytest.mark.parametrize(
    "body",
    [
        {"code": "NOPE", "quantity": 10, "avg_price": 1},
        {"code": CODE, "quantity": 0, "avg_price": 1},
        {"code": CODE, "quantity": 10, "avg_price": 0},
        {"code": CODE, "quantity": -5, "avg_price": 1},
    ],
)
def test_invalid_registrations_are_rejected(
    market_client: TestClient, body: dict[str, Any]
) -> None:
    assert market_client.post("/api/holdings", json=body).status_code == 422
    assert market_client.get("/api/holdings").json() == []


def test_a_sale_moves_the_holding_to_rebuy_wait_with_the_target_price(
    market_client: TestClient,
) -> None:
    use_hand_rates(market_client)
    holding = create(market_client)

    response = fill(market_client, holding["id"], "sell", 100_000, 30)

    assert response.status_code == 201
    body = response.json()
    assert body["fill"]["fee"] == 450.0
    assert body["fill"]["tax"] == 5400.0
    assert body["cycle"]["state"] == "rebuy_wait"
    assert body["cycle"]["rebuy_target_price"] == 98_790.0
    assert body["cycle"]["expires_at"] is not None
    assert body["holding"]["state"] == "rebuy_wait"
    assert body["holding"]["quantity"] == 70
    assert body["holding"]["open_cycle"]["id"] == body["cycle"]["id"]


def test_the_full_cycle_gains_a_share_after_costs(market_client: TestClient) -> None:
    use_hand_rates(market_client)
    holding = create(market_client)
    fill(market_client, holding["id"], "sell", 100_000, 30)

    response = fill(market_client, holding["id"], "rebuy", 95_000, 31)

    body = response.json()
    assert body["cycle"]["state"] == "rebuy_done"
    assert body["cycle"]["quantity_increase"] == 1
    assert body["cycle"]["net_cash"] == 48_708.25
    assert body["holding"]["state"] == "holding"
    assert body["holding"]["quantity"] == 101
    assert body["holding"]["cumulative_increase"] == 1

    cycles = market_client.get(f"/api/holdings/{holding['id']}/cycles").json()
    assert cycles["holding_id"] == holding["id"]
    assert [c["quantity_increase"] for c in cycles["cycles"]] == [1]
    assert cycles["totals"] == {
        "cycles": 1,
        "completed": 1,
        "successful": 1,
        "cumulative_increase": 1,
        "unrecovered_quantity": 0,
        "pending_quantity": 0,
        "start_quantity": 100,
        "current_quantity": 101,
    }


def test_cycles_carry_the_fill_times_for_the_chart_markers(market_client: TestClient) -> None:
    holding = create(market_client)
    sold = "2026-10-16T10:00:10"
    rebought = "2026-10-16T13:00:10"
    fill(market_client, holding["id"], "sell", 100_000, 30, filled_at=f"{sold}+09:00")

    (waiting,) = market_client.get(f"/api/holdings/{holding['id']}/cycles").json()["cycles"]
    assert waiting["sold_at"][:19] == sold  # SQLite drops the offset, PostgreSQL keeps it
    assert (waiting["rebought_at"], waiting["forced"]) == (None, False)

    fill(market_client, holding["id"], "rebuy", 95_000, 31, filled_at=f"{rebought}+09:00")
    (done,) = market_client.get(f"/api/holdings/{holding['id']}/cycles").json()["cycles"]
    assert (done["sold_at"][:19], done["rebought_at"][:19]) == (sold, rebought)


def test_a_forced_sale_is_marked_on_its_cycle(market_client: TestClient) -> None:
    holding = create(market_client)
    fill(market_client, holding["id"], "sell", 100_000, 100, forced=True)

    (cycle,) = market_client.get(f"/api/holdings/{holding['id']}/cycles").json()["cycles"]

    assert cycle["forced"] is True
    assert cycle["state"] == "force_closed"


def test_the_second_sale_of_a_cycle_is_a_conflict(market_client: TestClient) -> None:
    holding = create(market_client)
    fill(market_client, holding["id"], "sell", 100_000, 30)

    response = fill(market_client, holding["id"], "sell", 100_000, 10)

    assert response.status_code == 409
    assert "One sale per cycle" in response.json()["detail"]


def test_a_rebuy_without_a_sale_is_a_conflict(market_client: TestClient) -> None:
    holding = create(market_client)

    assert fill(market_client, holding["id"], "rebuy", 95_000, 31).status_code == 409


def test_selling_more_than_is_held_is_rejected(market_client: TestClient) -> None:
    holding = create(market_client)

    assert fill(market_client, holding["id"], "sell", 100_000, 101).status_code == 422
    assert fill(market_client, holding["id"], "sell", 100_000, 0).status_code == 422
    assert fill(market_client, holding["id"], "sell", 0, 10).status_code == 422
    assert market_client.get(f"/api/holdings/{holding['id']}/cycles").json()["cycles"] == []


def test_unknown_holdings_and_cycles_are_404(market_client: TestClient) -> None:
    holding = create(market_client)

    assert fill(market_client, 9999, "sell", 1, 1).status_code == 404
    assert market_client.get("/api/holdings/9999/cycles").status_code == 404
    assert (
        market_client.post(f"/api/holdings/{holding['id']}/cycles/9999/abandon").status_code == 404
    )
    assert market_client.delete("/api/holdings/9999").status_code == 404


def test_fees_can_be_entered_by_hand(market_client: TestClient) -> None:
    holding = create(market_client)

    body = fill(market_client, holding["id"], "sell", 100_000, 30, fee=1000, tax=2000).json()

    assert (body["fill"]["fee"], body["fill"]["tax"]) == (1000.0, 2000.0)
    assert body["cycle"]["sell_fee"] == 1000.0


def test_abandoning_a_cycle(market_client: TestClient) -> None:
    holding = create(market_client)
    cycle_id = fill(market_client, holding["id"], "sell", 100_000, 30).json()["cycle"]["id"]

    response = market_client.post(f"/api/holdings/{holding['id']}/cycles/{cycle_id}/abandon")

    assert response.status_code == 200
    assert response.json()["state"] == "abandoned"
    after = market_client.get("/api/holdings").json()[0]
    assert (after["state"], after["quantity"], after["unrecovered_quantity"]) == ("holding", 70, 30)
    assert (
        market_client.post(f"/api/holdings/{holding['id']}/cycles/{cycle_id}/abandon").status_code
        == 409
    )


def test_retrying_is_only_possible_after_expiry(market_client: TestClient) -> None:
    holding = create(market_client)
    cycle_id = fill(market_client, holding["id"], "sell", 100_000, 30).json()["cycle"]["id"]

    assert (
        market_client.post(f"/api/holdings/{holding['id']}/cycles/{cycle_id}/retry").status_code
        == 409
    )


def test_a_forced_sale_closes_the_cycle_and_empties_the_position(market_client: TestClient) -> None:
    holding = create(market_client)
    fill(market_client, holding["id"], "sell", 100_000, 30)

    body = fill(market_client, holding["id"], "sell", 98_000, 70, forced=True).json()

    assert body["fill"]["forced"] is True
    assert body["cycle"]["state"] == "force_closed"
    assert body["holding"]["quantity"] == 0
    assert body["holding"]["state"] == "holding"


def test_a_registration_can_be_corrected_until_a_cycle_opens(market_client: TestClient) -> None:
    holding = create(market_client)

    fixed = market_client.put(
        f"/api/holdings/{holding['id']}", json={"quantity": 120, "avg_price": 88_000}
    )
    assert fixed.status_code == 200
    assert (fixed.json()["quantity"], fixed.json()["start_quantity"]) == (120, 120)

    fill(market_client, holding["id"], "sell", 100_000, 30)
    again = market_client.put(
        f"/api/holdings/{holding['id']}", json={"quantity": 1, "avg_price": 1}
    )
    assert again.status_code == 409


def test_deleting_a_holding_removes_its_history(market_client: TestClient) -> None:
    holding = create(market_client)
    fill(market_client, holding["id"], "sell", 100_000, 30)

    assert market_client.delete(f"/api/holdings/{holding['id']}").status_code == 204

    assert market_client.get("/api/holdings").json() == []
    assert market_client.get(f"/api/holdings/{holding['id']}/cycles").status_code == 404
