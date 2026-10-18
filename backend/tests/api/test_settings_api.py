import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engine.params import DEFAULT_PARAMS
from app.services import settings as service


def current(client: TestClient) -> dict[str, Any]:
    return dict(client.get("/api/settings").json())


def document(settings: dict[str, Any]) -> dict[str, Any]:
    """A copy of the editable part of a response (what PUT takes)."""
    return copy.deepcopy({k: v for k, v in settings.items() if k != "presets"})


def test_settings_require_a_login(client: TestClient) -> None:
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={}).status_code == 401
    assert client.post("/api/settings/presets", json={"name": "x"}).status_code == 401
    assert client.post("/api/settings/presets/x/load").status_code == 401
    assert client.delete("/api/settings/presets/x").status_code == 401


def test_the_defaults_are_the_prd_values(market_client: TestClient) -> None:
    body = current(market_client)

    assert body["signal_params"] == DEFAULT_PARAMS.model_dump(mode="json")
    assert body["signal_bar_length"] == "60m"
    assert body["alert_cooldown_bars"] == 6
    assert body["channels"] == {"telegram": False}
    assert body["refresh_seconds"] == 60
    assert body["presets"] == []


def test_every_part_of_the_settings_can_be_saved_and_read_back(market_client: TestClient) -> None:
    changed = current(market_client)
    changed["signal_params"]["rebuy"]["round_trip_fee_rate"] = 0.0005
    changed["signal_params"]["rebuy"]["sell_tax_rate"] = 0.002
    changed["signal_params"]["screener"]["drawdown_threshold_pct"] = -25
    changed["signal_bar_length"] = "30m"
    changed["alert_cooldown_bars"] = 3
    changed["channels"] = {"telegram": True}
    changed["refresh_seconds"] = 30

    response = market_client.put("/api/settings", json=document(changed))

    assert response.status_code == 200
    assert document(response.json()) == document(changed)
    assert document(current(market_client)) == document(changed)


def test_saved_settings_reach_the_services(market_client: TestClient, market: Session) -> None:
    changed = current(market_client)
    changed["signal_params"]["scan"]["min_score"] = 55
    changed["signal_bar_length"] = "1d"
    market_client.put("/api/settings", json=document(changed))

    market.expire_all()
    assert service.load_signal_params(market).scan.min_score == 55
    assert service.load_signal_bar_length(market).value == "1d"


def test_polling_can_be_switched_off(market_client: TestClient) -> None:
    body = document(current(market_client))
    body["refresh_seconds"] = 0

    assert market_client.put("/api/settings", json=body).json()["refresh_seconds"] == 0


@pytest.mark.parametrize("seconds", [1, 9, 3601, -5])
def test_a_polling_period_outside_the_range_is_rejected(
    market_client: TestClient, seconds: int
) -> None:
    body = document(current(market_client))
    body["refresh_seconds"] = seconds

    assert market_client.put("/api/settings", json=body).status_code == 422
    assert current(market_client)["refresh_seconds"] == 60


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("signal_params", "rebuy", "round_trip_fee_rate"), -0.1),
        (("signal_params", "indicators", "rsi_period"), 1),
        (("signal_params", "sell", "sell_fraction"), 1.0),
        (("alert_cooldown_bars",), -1),
        (("alert_cooldown_bars",), 501),
        (("signal_bar_length",), "5m"),
        (("channels",), {"sms": True}),
    ],
)
def test_invalid_values_are_rejected_and_nothing_changes(
    market_client: TestClient, path: tuple[str, ...], value: object
) -> None:
    before = current(market_client)
    body = document(before)
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert market_client.put("/api/settings", json=body).status_code == 422
    assert current(market_client) == before


def test_unknown_fields_are_rejected(market_client: TestClient) -> None:
    body = document(current(market_client))
    body["signal_params"]["screener"]["drawdown_treshold_pct"] = -20  # a typo

    assert market_client.put("/api/settings", json=body).status_code == 422


def test_a_missing_part_is_rejected(market_client: TestClient) -> None:
    body = document(current(market_client))
    del body["alert_cooldown_bars"]

    assert market_client.put("/api/settings", json=body).status_code == 422


# --- presets -----------------------------------------------------------------------------------


def tweak(client: TestClient, min_score: float, bar_length: str = "60m") -> None:
    body = document(current(client))
    body["signal_params"]["scan"]["min_score"] = min_score
    body["signal_bar_length"] = bar_length
    client.put("/api/settings", json=body)


def test_a_preset_is_saved_listed_loaded_and_deleted(market_client: TestClient) -> None:
    tweak(market_client, 40, "30m")
    created = market_client.post("/api/settings/presets", json={"name": "공격적"})
    assert created.status_code == 201
    assert created.json()["name"] == "공격적"

    tweak(market_client, 70, "1d")
    assert [p["name"] for p in current(market_client)["presets"]] == ["공격적"]

    loaded = market_client.post("/api/settings/presets/공격적/load")
    assert loaded.status_code == 200
    assert loaded.json()["signal_params"]["scan"]["min_score"] == 40
    assert loaded.json()["signal_bar_length"] == "30m"
    assert current(market_client)["signal_params"]["scan"]["min_score"] == 40

    assert market_client.delete("/api/settings/presets/공격적").status_code == 204
    assert current(market_client)["presets"] == []


def test_a_preset_keeps_the_tunables_but_not_the_channels_or_polling(
    market_client: TestClient,
) -> None:
    body = document(current(market_client))
    body["channels"] = {"telegram": True}
    body["refresh_seconds"] = 30
    market_client.put("/api/settings", json=body)
    market_client.post("/api/settings/presets", json={"name": "a"})

    body["channels"] = {"telegram": False}
    body["refresh_seconds"] = 0
    market_client.put("/api/settings", json=body)
    loaded = market_client.post("/api/settings/presets/a/load").json()

    assert loaded["channels"] == {"telegram": False}
    assert loaded["refresh_seconds"] == 0


def test_saving_a_preset_under_an_existing_name_replaces_it(market_client: TestClient) -> None:
    tweak(market_client, 10)
    market_client.post("/api/settings/presets", json={"name": "x"})
    tweak(market_client, 90)
    market_client.post("/api/settings/presets", json={"name": "x"})
    tweak(market_client, 0)

    loaded = market_client.post("/api/settings/presets/x/load").json()

    assert loaded["signal_params"]["scan"]["min_score"] == 90
    assert len(current(market_client)["presets"]) == 1


def test_presets_are_listed_by_name(market_client: TestClient) -> None:
    for name in ("b", "a", "c"):
        market_client.post("/api/settings/presets", json={"name": name})

    assert [p["name"] for p in current(market_client)["presets"]] == ["a", "b", "c"]


@pytest.mark.parametrize("name", ["", "   ", "a/b", "a\\b", "x" * 41])
def test_bad_preset_names_are_rejected(market_client: TestClient, name: str) -> None:
    assert market_client.post("/api/settings/presets", json={"name": name}).status_code == 422
    assert current(market_client)["presets"] == []


def test_unknown_presets_are_404(market_client: TestClient) -> None:
    assert market_client.post("/api/settings/presets/nope/load").status_code == 404
    assert market_client.delete("/api/settings/presets/nope").status_code == 404


def test_preset_names_cannot_clash_with_the_settings_rows(
    market_client: TestClient, market: Session
) -> None:
    from app.db.models import Setting

    market_client.post("/api/settings/presets", json={"name": "current"})
    market_client.post("/api/settings/presets", json={"name": "collection_status"})

    names = {row.name for row in market.query(Setting).all()}
    assert {"preset:current", "preset:collection_status"} <= names
    assert [p["name"] for p in current(market_client)["presets"]] == [
        "collection_status",
        "current",
    ]
    assert current(market_client)["signal_params"] == DEFAULT_PARAMS.model_dump(mode="json")
