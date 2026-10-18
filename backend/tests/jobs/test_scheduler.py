from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from apscheduler.triggers.cron import CronTrigger
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.adapters.mock import MockAdapter
from app.core.config import Settings, get_settings
from app.core.market import KST
from app.jobs import scheduler as scheduler_module
from app.jobs.monitor import JobContext, JobResult
from app.jobs.scheduler import DAILY_JOB, INTRADAY_JOB, build_scheduler, run_daily, run_intraday
from tests.conftest import sqlite_engine


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


@pytest.fixture
def ctx() -> JobContext:
    return JobContext(
        sessionmaker(bind=sqlite_engine()), MockAdapter(seed=1, n_kospi=3, n_kosdaq=2), Settings()
    )


def fires(trigger: CronTrigger, start: str, count: int) -> list[str]:
    moments, previous = [], None
    now = at(start)
    for _ in range(count):
        previous = trigger.get_next_fire_time(
            previous, previous + timedelta(seconds=1) if previous else now
        )
        assert previous is not None
        moments.append(previous.astimezone(KST).strftime("%a %m-%d %H:%M:%S"))
    return moments


def test_both_jobs_are_registered_in_korean_time(ctx: JobContext) -> None:
    scheduler = build_scheduler(ctx)

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {INTRADAY_JOB, DAILY_JOB}
    assert str(scheduler.timezone) == "Asia/Seoul"
    for job in jobs.values():
        assert job.max_instances == 1  # a slow run is never overlapped by the next
        assert job.coalesce is True  # missed runs are merged into one
        assert job.args == (ctx,)


def test_the_intraday_job_fires_ten_seconds_after_every_bar_close_on_weekdays(
    ctx: JobContext,
) -> None:
    job = build_scheduler(ctx).get_job(INTRADAY_JOB)
    assert job is not None

    friday = fires(job.trigger, "2026-10-16 08:00:00", 14)

    assert friday[0] == "Fri 10-16 09:00:10"  # no bar has closed yet: the job skips this one
    assert friday[1] == "Fri 10-16 09:30:10"
    assert friday[-1] == "Fri 10-16 15:30:10"  # the close of the last bar
    assert len(friday) == 14
    after_close = fires(job.trigger, "2026-10-16 15:31:00", 2)
    assert after_close == ["Mon 10-19 09:00:10", "Mon 10-19 09:30:10"]  # not on the weekend


def test_the_daily_job_fires_once_after_the_close_at_the_scan_time(ctx: JobContext) -> None:
    job = build_scheduler(ctx).get_job(DAILY_JOB)
    assert job is not None

    assert fires(job.trigger, "2026-10-16 12:00:00", 3) == [
        "Fri 10-16 18:00:00",
        "Mon 10-19 18:00:00",
        "Tue 10-20 18:00:00",
    ]


def test_the_daily_job_follows_the_configured_scan_time() -> None:
    settings = Settings(daily_scan_time="19:15")
    scheduler = build_scheduler(
        JobContext(sessionmaker(bind=sqlite_engine()), MockAdapter(seed=1), settings)
    )
    job = scheduler.get_job(DAILY_JOB)
    assert job is not None

    assert fires(job.trigger, "2026-10-16 12:00:00", 1) == ["Fri 10-16 19:15:00"]


def test_building_a_scheduler_does_not_start_it(ctx: JobContext) -> None:
    assert build_scheduler(ctx).running is False


# --- the wrappers the scheduler calls -------------------------------------------------------------


def test_a_crashing_job_is_logged_and_does_not_stop_the_scheduler(
    ctx: JobContext, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(_: JobContext) -> JobResult:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(scheduler_module, "run_intraday_job", boom)
    monkeypatch.setattr(scheduler_module, "run_daily_job", boom)

    run_intraday(ctx)  # must not raise
    run_daily(ctx)

    assert caplog.text.count("job crashed") == 2


def test_a_skipped_job_says_why(
    ctx: JobContext, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        scheduler_module, "run_intraday_job", lambda _: JobResult(skipped="not a trading day")
    )

    run_intraday(ctx)

    assert "intraday job skipped: not a trading day" in caplog.text


# --- the app starts and stops the scheduler -------------------------------------------------------


class FakeScheduler:
    def __init__(self) -> None:
        self.running = False
        self.log: list[str] = []

    def start(self) -> None:
        self.running = True
        self.log.append("start")

    def shutdown(self, wait: bool = True) -> None:
        self.running = False
        self.log.append("shutdown")

    def get_jobs(self) -> list[Any]:
        return []


@pytest.fixture
def scheduler_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeScheduler]:
    fake = FakeScheduler()
    from app import main

    monkeypatch.setattr(main, "build_scheduler", lambda ctx: fake)
    yield fake
    get_settings.cache_clear()


def app_with_database() -> Any:
    from app.db.session import get_db
    from app.main import create_app

    factory = sessionmaker(bind=sqlite_engine())

    def override() -> Iterator[Any]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override
    return app


def test_the_scheduler_is_off_unless_it_is_enabled(scheduler_env: FakeScheduler) -> None:
    with TestClient(app_with_database()) as client:
        assert client.get("/api/health").json()["scheduler"] == "disabled"

    assert scheduler_env.log == []


def test_the_scheduler_runs_with_the_app_when_enabled(
    scheduler_env: FakeScheduler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    get_settings.cache_clear()

    with TestClient(app_with_database()) as client:
        assert client.get("/api/health").json()["scheduler"] == "running"
        assert scheduler_env.log == ["start"]

    assert scheduler_env.log == ["start", "shutdown"]
