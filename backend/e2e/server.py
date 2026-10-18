"""``uvicorn e2e.server:create_e2e_app --factory``: the real API plus a few test controls.

The controls (under ``/api/_e2e``) move the mock clock, run the scheduled jobs on it, pin the
signals and rebuild the database. Everything else is the application as it runs in production,
on its own PostgreSQL database.
"""

import os
from datetime import datetime
from typing import Any, Literal

from alembic.config import Config
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import REPO_ROOT, get_settings
from app.main import create_app
from e2e import signals
from e2e.world import World

router = APIRouter(prefix="/_e2e", tags=["e2e"])
_world: World | None = None


class ClockBody(BaseModel):
    now: datetime


class TickBody(BaseModel):
    job: Literal["intraday", "daily"] = "intraday"


class SignalsBody(BaseModel):
    sell: bool | None = None
    rebuy: bool | None = None
    flow: Literal["off", "exit", "missing"] | None = None
    force_sell: bool | None = None


def world() -> World:
    global _world
    if _world is None:
        _world = World()
    return _world


@router.post("/reset")
def reset() -> dict[str, Any]:
    scenario = world().reset()
    return {
        "holding_id": scenario.holding_id,
        "code": scenario.code,
        "name": scenario.name,
        "now": world().clock.now.isoformat(),
    }


@router.post("/clock")
def set_clock(body: ClockBody) -> dict[str, str]:
    world().clock.set(body.now)
    return {"now": world().clock.now.isoformat()}


@router.post("/tick")
def tick(body: TickBody) -> dict[str, Any]:
    return {"now": world().clock.now.isoformat(), **world().tick(body.job)}


@router.post("/signals")
def set_signals(body: SignalsBody) -> dict[str, Any]:
    for name, value in body.model_dump(exclude_none=True).items():
        setattr(signals.pins, name, value)
    return {"sell": signals.pins.sell, "rebuy": signals.pins.rebuy, "flow": signals.pins.flow,
            "force_sell": signals.pins.force_sell}  # fmt: skip


def _prepare_database() -> None:
    """Create the ``*_e2e`` database if it is missing and bring it to the latest migration."""
    url = make_url(get_settings().database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    backend = REPO_ROOT / "backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    command.upgrade(config, "head")


def create_e2e_app() -> FastAPI:
    if os.environ.get("E2E_MODE") != "1":
        raise RuntimeError("set E2E_MODE=1: this server rewrites its database on demand")
    database = make_url(get_settings().database_url).database or ""
    if not database.endswith("_e2e"):
        raise RuntimeError(f"refusing to run on database {database!r}: its name must end in _e2e")
    _prepare_database()
    app = create_app()
    app.include_router(router, prefix="/api")
    return app
