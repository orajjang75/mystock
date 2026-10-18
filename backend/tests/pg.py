"""Helpers for tests that need a real PostgreSQL server (``docker compose up -d``)."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

ADMIN_URL = os.environ.get(
    "TEST_POSTGRES_ADMIN_URL", "postgresql+psycopg://mystock:mystock@localhost:5432/postgres"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]


@contextmanager
def fresh_database(name: str) -> Iterator[URL]:
    """Create an empty database for the duration of the block; skip the test if unreachable."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {name}"))
    except OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL is not reachable (run `docker compose up -d`)")
    try:
        yield make_url(ADMIN_URL).set(database=name)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


def alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    return config
