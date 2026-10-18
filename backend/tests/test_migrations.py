"""Run the Alembic migrations against a real PostgreSQL server (docker compose up).

Skipped when the server is unreachable. Override the admin URL with TEST_POSTGRES_ADMIN_URL.
"""

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

from alembic import command
from app.db.base import Base
from tests.pg import alembic_config, fresh_database


@pytest.fixture
def postgres_url() -> Iterator[URL]:
    with fresh_database("mystock_migration_test") as url:
        yield url


def test_upgrade_head_matches_models_and_downgrades(postgres_url: URL) -> None:
    config = alembic_config(postgres_url)

    command.upgrade(config, "head")

    engine = create_engine(postgres_url)
    try:
        assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set(
            Base.metadata.tables
        )
        # The migration must produce exactly the schema the models describe.
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == []
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(postgres_url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
