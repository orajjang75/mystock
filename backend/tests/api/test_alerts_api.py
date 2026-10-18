from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import alerts as alerts_api
from app.core.market import KST
from app.db.enums import BarLength, Market
from app.db.models import Instrument
from app.services.alert_engine import AlertDraft
from app.services.alerts import save_drafts
from app.services.notifier import Notification, Notifier, NotifierError
from app.services.settings import save_channels


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


@pytest.fixture
def seeded(client: TestClient, db: Session) -> TestClient:
    db.add_all(
        [
            Instrument(code="900010", name="모의KOSPI001", market=Market.KOSPI),
            Instrument(code="900020", name="모의KOSPI002", market=Market.KOSPI),
        ]
    )
    db.flush()
    drafts: list[tuple[str, str, str, dict[str, Any]]] = [
        ("sell", "900010", "09:00", {"rsi": 68.2}),
        ("rebuy", "900010", "10:00", {"confirmations": 2}),
        ("rebuy_held", "900020", "11:00", {"held_by_flow_filter": True}),
        ("stop_loss", "900020", "12:00", {"stop_price": 100.0}),
    ]
    for i, (kind, code, hhmm, evidence) in enumerate(drafts):
        draft = AlertDraft(
            kind=kind,
            holding_id=None,
            code=code,
            bar_time=at(f"2026-10-16 {hhmm}"),
            bar_length=BarLength.M60,
            bar_end=at(f"2026-10-16 {hhmm}").replace(hour=int(hhmm[:2]) + 1),
            suggested_quantity=33 if kind == "sell" else None,
            price=67_405.0,
            evidence=evidence,
            params={"sell": {"min_overlap": 2}},
        )
        save_drafts(
            db,
            [draft],
            created_at=at(f"2026-10-16 1{i}:00:10"),
            cooldown_bars=6,
            signal_length=BarLength.M60,
        )
    db.commit()
    return client


def test_alerts_require_a_login(client: TestClient) -> None:
    assert client.get("/api/alerts").status_code == 401
    assert client.post("/api/alerts/1/read").status_code == 401
    assert client.post("/api/alerts/test").status_code == 401


def logged_in(client: TestClient) -> TestClient:
    client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
    return client


def test_the_list_is_newest_first_with_labels_names_and_evidence(seeded: TestClient) -> None:
    body = logged_in(seeded).get("/api/alerts").json()

    assert body["unread"] == 4
    assert [a["kind"] for a in body["items"]] == ["stop_loss", "rebuy_held", "rebuy", "sell"]
    first, *_, sell = body["items"]
    assert first["label"] == "손절선 이탈 경고"
    assert first["name"] == "모의KOSPI002"
    assert first["evidence"] == {
        "stop_price": 100.0,
        "latency_seconds": first["evidence"]["latency_seconds"],
        "bar_end": first["evidence"]["bar_end"],
    }
    assert sell["suggested_quantity"] == 33
    assert sell["price"] == 67_405.0
    assert sell["evidence"]["rsi"] == 68.2
    assert sell["is_read"] is False


def test_the_kinds_the_filter_offers_come_with_the_response(seeded: TestClient) -> None:
    kinds = logged_in(seeded).get("/api/alerts", params={"kind": "sell"}).json()["kinds"]

    by_kind = {k["kind"]: k for k in kinds}
    assert "test" not in by_kind  # a channel check, not a signal
    assert by_kind["sell"] == {"kind": "sell", "label": "매도 신호", "level": "signal"}
    assert by_kind["rebuy_held"]["label"] == "재매수 보류 경고 (일봉 수급 이탈)"
    assert by_kind["rebuy_held"]["level"] == "warning"
    assert list(by_kind)[:2] == ["sell", "rebuy"]  # the filter does not shrink with the result


def test_warnings_are_marked_apart_from_signals(seeded: TestClient) -> None:
    items = logged_in(seeded).get("/api/alerts").json()["items"]

    assert {a["kind"]: a["level"] for a in items} == {
        "stop_loss": "warning",
        "rebuy_held": "warning",
        "rebuy": "signal",
        "sell": "signal",
    }


def test_the_used_parameters_are_only_returned_on_request(seeded: TestClient) -> None:
    client = logged_in(seeded)

    assert client.get("/api/alerts").json()["items"][0]["params"] is None
    detailed = client.get("/api/alerts", params={"include_params": True}).json()["items"][0]
    assert detailed["params"] == {"sell": {"min_overlap": 2}}


def test_filters_by_kind_stock_and_unread(seeded: TestClient) -> None:
    client = logged_in(seeded)
    items = client.get("/api/alerts").json()["items"]
    client.post(f"/api/alerts/{items[-1]['id']}/read")  # the oldest, the sell

    assert [
        a["kind"] for a in client.get("/api/alerts", params={"kind": "rebuy"}).json()["items"]
    ] == ["rebuy"]
    by_code = client.get("/api/alerts", params={"code": "900020"}).json()["items"]
    assert {a["kind"] for a in by_code} == {"rebuy_held", "stop_loss"}
    unread = client.get("/api/alerts", params={"unread_only": True}).json()
    assert unread["unread"] == 3
    assert "sell" not in [a["kind"] for a in unread["items"]]


def test_paging_and_its_limits(seeded: TestClient) -> None:
    client = logged_in(seeded)

    page = client.get("/api/alerts", params={"limit": 2, "offset": 1}).json()["items"]

    assert [a["kind"] for a in page] == ["rebuy_held", "rebuy"]
    assert client.get("/api/alerts", params={"limit": 0}).status_code == 422
    assert client.get("/api/alerts", params={"limit": 201}).status_code == 422
    assert client.get("/api/alerts", params={"offset": -1}).status_code == 422


def test_reading_an_alert_marks_it_and_lowers_the_unread_count(seeded: TestClient) -> None:
    client = logged_in(seeded)
    alert_id = client.get("/api/alerts").json()["items"][0]["id"]

    response = client.post(f"/api/alerts/{alert_id}/read")
    again = client.post(f"/api/alerts/{alert_id}/read")

    assert response.status_code == 200
    assert response.json()["is_read"] is True
    assert again.status_code == 200  # idempotent
    assert client.get("/api/alerts").json()["unread"] == 3


def test_reading_an_unknown_alert_is_404(seeded: TestClient) -> None:
    assert logged_in(seeded).post("/api/alerts/99999/read").status_code == 404


# --- the test message --------------------------------------------------------------------------


class Fake(Notifier):
    name = "fake"

    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        if self.fail:
            raise NotifierError(self.fail)
        self.sent.append(notification)


def test_the_test_message_needs_a_channel(client: TestClient) -> None:
    response = logged_in(client).post("/api/alerts/test")

    assert response.status_code == 409
    assert "No outside channel" in response.json()["detail"]


def test_the_test_message_goes_to_every_enabled_channel(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = Fake()
    monkeypatch.setattr(alerts_api, "build_notifiers", lambda settings, channels: [fake])

    response = logged_in(client).post("/api/alerts/test")

    assert response.status_code == 200
    assert response.json() == {"channels": [{"channel": "fake", "status": "sent"}]}
    assert fake.sent[0].text.startswith("[시험 알림]")


def test_a_failing_channel_is_reported_not_raised(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        alerts_api,
        "build_notifiers",
        lambda s, c: [Fake(fail="telegram rejected the message (HTTP 401)")],
    )

    body: dict[str, Any] = logged_in(client).post("/api/alerts/test").json()

    assert body["channels"] == [
        {"channel": "fake", "status": "failed", "error": "telegram rejected the message (HTTP 401)"}
    ]


def test_the_channel_settings_decide_which_notifiers_are_built(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, bool]] = []

    def spy(settings: Any, channels: dict[str, bool]) -> list[Notifier]:
        seen.append(channels)
        return [Fake()]

    monkeypatch.setattr(alerts_api, "build_notifiers", spy)
    save_channels(db, {"telegram": True})
    db.commit()

    logged_in(client).post("/api/alerts/test")

    assert seen == [{"telegram": True}]
