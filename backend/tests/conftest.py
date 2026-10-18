import os
from collections.abc import Iterator

# Settings are read from the environment; set them before the app modules are imported so
# the tests never depend on (or leak) a developer's .env.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["APP_USERNAME"] = "tester"
os.environ["APP_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-0123"
os.environ["COOKIE_SECURE"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, StaticPool, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app()
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


# --- shared fixtures for the market-data tests -------------------------------------------

from datetime import date  # noqa: E402

from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.adapters.mock import MockAdapter  # noqa: E402
from tests.pg import alembic_config, fresh_database  # noqa: E402

END_DATE = date(2026, 10, 16)  # a Friday


@pytest.fixture(scope="session")
def mock_adapter() -> MockAdapter:
    """The full-size mock market. Read-only: tests must not mutate it."""
    return MockAdapter(seed=42, end_date=END_DATE)


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    with fresh_database("mystock_data_test") as url:
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url)
        yield engine
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def session(request: pytest.FixtureRequest) -> Iterator[Session]:
    """A session on an empty database, once per backend (SQLite and real PostgreSQL)."""
    if request.param == "sqlite":
        engine: Engine = request.getfixturevalue("engine")
    else:
        engine = request.getfixturevalue("pg_engine")
    with sessionmaker(bind=engine, expire_on_commit=False)() as db_session:
        yield db_session
        db_session.rollback()
    if request.param == "postgres":
        tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


# --- a fully ingested mock market, shared by the screener tests ---------------------------

from datetime import datetime  # noqa: E402

from sqlalchemy import delete  # noqa: E402

from app.core.market import KST  # noqa: E402
from app.db.models import (  # noqa: E402
    Alert,
    Cycle,
    Fill,
    Holding,
    ScanResult,
    Setting,
    Watchlist,
)
from app.jobs.ingest import run_ingest  # noqa: E402

AFTER_CLOSE = datetime(2026, 10, 16, 16, 0, tzinfo=KST)


def sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _clean_results(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as cleaner:
        for table in (Fill, Cycle, Holding, Alert, ScanResult, Watchlist, Setting):
            cleaner.execute(delete(table))
        cleaner.commit()


@pytest.fixture(scope="session")
def market_engine(mock_adapter: MockAdapter) -> Engine:
    """SQLite with the full mock market ingested (KOSPI 100 + KOSDAQ 20). Ingested once."""
    engine = sqlite_engine()
    with sessionmaker(bind=engine, expire_on_commit=False)() as db_session:
        run_ingest(db_session, mock_adapter, as_of=END_DATE, now=AFTER_CLOSE)
    return engine


@pytest.fixture
def market(market_engine: Engine) -> Iterator[Session]:
    """A session on the shared market; scan results, watchlist and settings are wiped after."""
    with sessionmaker(bind=market_engine, expire_on_commit=False)() as db_session:
        yield db_session
    _clean_results(market_engine)


@pytest.fixture
def market_client(market_engine: Engine) -> Iterator[TestClient]:
    """A logged-in API client on the shared market."""
    app = create_app()
    factory = sessionmaker(bind=market_engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login", json={"username": "tester", "password": "test-password"}
        )
        assert login.status_code == 200
        yield client
    _clean_results(market_engine)
