"""Backtest runs: created through the API, executed on a worker thread, stored in backtest_runs.

A run goes ``queued`` -> ``running`` -> ``done`` (or ``failed`` with the reason). The worker opens
its own database session, so a long run never holds the request that started it. Runs that were
still going when the server stopped are marked failed at the next start.
"""

import logging
import re
from collections.abc import Callable
from concurrent.futures import Executor
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.config import BacktestConfig
from app.backtest.report import build_report
from app.backtest.runner import run_backtest
from app.db.enums import BarLength
from app.db.models import BacktestRun
from app.engine.params import SignalParams
from app.services import settings as settings_service

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
PRESET_NAME_LIMIT = 40


class RunNotFoundError(LookupError):
    pass


def create_run(session: Session, config: BacktestConfig) -> BacktestRun:
    """Store a queued run holding the whole request. Commits."""
    run = BacktestRun(
        start_date=config.start_date or date.today(),  # replaced by the real period when done
        end_date=config.end_date or date.today(),
        bar_length=config.bar_length,
        params=config.model_dump(mode="json"),
        summary={},
        detail={},
        name=config.name,
        status="queued",
        progress=0.0,
    )
    session.add(run)
    session.commit()
    return run


def get_run(session: Session, run_id: int) -> BacktestRun:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def list_runs(session: Session, limit: int = 50) -> list[BacktestRun]:
    return list(session.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit)))


def delete_run(session: Session, run_id: int) -> None:
    session.delete(get_run(session, run_id))
    session.commit()


def fail_interrupted(session: Session) -> int:
    """At start-up: a run that was queued or running belongs to a process that is gone."""
    stuck = list(
        session.scalars(select(BacktestRun).where(BacktestRun.status.in_(("queued", "running"))))
    )
    for run in stuck:
        run.status = "failed"
        run.error = "interrupted: the server stopped before the run finished"
    session.commit()
    return len(stuck)


def execute_run(factory: SessionFactory, run_id: int) -> None:
    """Run one stored backtest and save its result. Never raises: a failure is stored."""
    with factory() as session:
        run = get_run(session, run_id)
        run.status, run.progress = "running", 0.01
        config = BacktestConfig.model_validate(run.params)
        session.commit()

        last = {"fraction": 0.0}

        def progress(fraction: float, message: str) -> None:
            if fraction - last["fraction"] < 0.01 and fraction < 1:
                return
            last["fraction"] = fraction
            run.progress = min(fraction, 0.99)
            run.summary = {"message": message}
            session.commit()

        try:
            summary, detail = run_backtest(session, config, progress)
        except Exception as error:
            session.rollback()
            logger.exception("backtest %s failed", run_id)
            run = get_run(session, run_id)
            run.status, run.error, run.progress = "failed", f"{type(error).__name__}: {error}", 1.0
            session.commit()
            return
        run = get_run(session, run_id)
        run.status, run.progress, run.error = "done", 1.0, None
        run.summary, run.detail = summary, detail
        period = summary["period"]
        run.start_date = date.fromisoformat(period["start"])
        run.end_date = date.fromisoformat(period["end"])
        session.commit()


def submit(executor: Executor, factory: SessionFactory, run_id: int) -> None:
    executor.submit(execute_run, factory, run_id)


def report_for(run: BacktestRun) -> str:
    if run.status != "done":
        raise ValueError("the run has not finished")
    return build_report(run.name, run.params, run.summary, run.detail)


def default_preset_name(run: BacktestRun) -> str:
    base = run.name or f"백테스트 #{run.id}"
    return re.sub(r"[/\\]", "-", base)[:PRESET_NAME_LIMIT]


def save_as_preset(session: Session, run: BacktestRun, name: str, *, apply: bool) -> None:
    """Keep the run's parameters as a preset; with ``apply`` also make them the current settings,
    which is what the screener and the alerts read. Commits."""
    config = BacktestConfig.model_validate(run.params)
    params: SignalParams = config.params
    settings_service.save_preset_values(session, name, params, BarLength(config.bar_length))
    if apply:
        settings_service.load_preset(session, name)
    session.commit()
