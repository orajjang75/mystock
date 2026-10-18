from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import current_time
from app.core.config import get_settings
from app.core.market import KST
from app.db.enums import Market
from app.db.models import Instrument, OhlcvDaily
from app.db.session import get_db
from app.main import create_app
from app.services import status
from app.services.settings import save_channels

SATURDAY = datetime(2026, 10, 17, 12, 0, tzinfo=KST)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


@pytest.fixture
def on_saturday(client: TestClient) -> TestClient:
    """The shared test client with the clock fixed on a Saturday noon."""
    client.app.dependency_overrides[current_time] = lambda: SATURDAY  # type: ignore[attr-defined]
    return client


def test_health_of_an_empty_system_has_no_times_and_a_collection_warning(
    on_saturday: TestClient,
) -> None:
    body = on_saturday.get("/api/health").json()

    assert on_saturday.get("/api/health").status_code == 200
    assert body["db"] == "ok"
    assert body["last_quote_update"] is None
    assert body["last_daily_update"] is None
    assert body["last_intraday_update"] is None
    assert body["latest_daily_date"] is None
    assert body["latest_intraday_bar"] is None
    assert body["scheduler"] == "disabled"
    # nothing was ever collected, so the daily data is stale
    assert body["status"] == "degraded"
    assert [w["source"] for w in body["warnings"]] == ["daily"]
    assert "일봉 시세" in body["warnings"][0]["message"]
    assert body["collection"]["daily"] == {"stale": True, "last_success": None, "last_error": None}
    assert body["collection"]["intraday"]["stale"] is False  # the market is closed


def test_health_is_ok_once_the_expected_collection_has_succeeded(
    on_saturday: TestClient, db: Session
) -> None:
    status.record_success(db, "daily", at("2026-10-16 18:00:20"))
    db.commit()

    body = on_saturday.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["warnings"] == []
    assert body["collection"]["daily"]["stale"] is False
    assert body["collection"]["daily"]["last_success"].startswith("2026-10-16T18:00:20")


def test_health_warns_when_the_intraday_collection_is_late(client: TestClient, db: Session) -> None:
    status.record_success(db, "daily", at("2026-10-15 18:00:20"))
    status.record_success(db, "intraday", at("2026-10-16 09:30:12"))
    db.commit()
    client.app.dependency_overrides[current_time] = lambda: at("2026-10-16 10:08")  # type: ignore[attr-defined]

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    (warning,) = body["warnings"]
    assert warning["source"] == "intraday"
    assert "10:00" in warning["message"]
    assert "분봉 시세" in warning["message"]


def test_health_shows_the_last_error_of_a_failed_collection(
    client: TestClient, db: Session
) -> None:
    status.record_success(db, "daily", at("2026-10-15 18:00:20"))
    status.record_success(db, "intraday", at("2026-10-16 09:30:12"))
    status.record_failure(db, "intraday", at("2026-10-16 10:00:15"), "ConnectionError: timeout")
    db.commit()
    client.app.dependency_overrides[current_time] = lambda: at("2026-10-16 10:00:30")  # type: ignore[attr-defined]

    body = client.get("/api/health").json()

    assert body["collection"]["intraday"]["last_error"] == "ConnectionError: timeout"
    assert body["collection"]["intraday"]["stale"] is True  # no waiting for a grace period


def test_health_reports_the_last_quote_update(on_saturday: TestClient, db: Session) -> None:
    db.add(Instrument(code="005930", name="삼성전자", market=Market.KOSPI))
    db.add(
        OhlcvDaily(
            code="005930",
            trade_date=date(2026, 10, 16),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=1000,
            trading_value=100_000,
            updated_at=datetime(2026, 10, 16, 7, 0, tzinfo=UTC),
        )
    )
    db.commit()

    body = on_saturday.get("/api/health").json()

    assert body["latest_daily_date"] == "2026-10-16"
    assert body["last_daily_update"].startswith("2026-10-16T07:00:00")
    assert body["last_quote_update"] == body["last_daily_update"]
    assert body["last_intraday_update"] is None


def test_health_lists_the_channels_without_their_secrets(
    on_saturday: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "123456789:AAH-health-secret-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "4242")
    get_settings.cache_clear()
    try:
        save_channels(db, {"telegram": True})
        db.commit()

        response = on_saturday.get("/api/health")

        assert response.json()["channels"] == {"telegram": {"enabled": True, "configured": True}}
        assert token not in response.text
        assert "4242" not in response.text
    finally:
        get_settings.cache_clear()


def test_health_needs_no_login(on_saturday: TestClient) -> None:
    assert on_saturday.get("/api/health").status_code == 200


def test_health_returns_503_when_database_is_down() -> None:
    class BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("postgresql://user:secret@host/db"))

    def broken_db() -> Iterator[BrokenSession]:
        yield BrokenSession()

    app = create_app()
    app.dependency_overrides[get_db] = broken_db
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert response.json()["status"] == "error"
    assert "secret" not in response.text
