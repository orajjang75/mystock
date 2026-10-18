"""POST/GET /api/backtests, the report and saving a run's parameters as a preset."""

from collections.abc import Callable, Iterator
from concurrent.futures import Executor, Future
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.api.backtests import get_executor, get_factory
from app.db.models import BacktestRun, ScanResult, Setting
from app.db.session import get_db
from app.engine.params import SignalParams
from app.main import create_app
from app.services.settings import load_signal_params, save_signal_params
from tests.conftest import sqlite_engine

QUICK: dict[str, Any] = {
    "signal_quality": {"random_trials": 2, "horizons": [5]},
    "cycle": {"max_stocks": 6, "min_sample_cycles": 3, "slippages": [0.0, 0.003]},
    "compare_bar_lengths": False,
    "bar_length": "1d",
}


class InlineExecutor(Executor):
    """Runs a submitted job at once, so a test sees the finished run."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class NeverExecutor(Executor):
    """Accepts jobs and never runs them: the run stays queued."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        return Future()


def make_client(engine: Engine, executor: Executor) -> Iterator[TestClient]:
    app = create_app()
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_executor] = lambda: executor
    app.dependency_overrides[get_factory] = lambda: factory
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
        yield client
    with factory() as cleanup:
        cleanup.execute(delete(BacktestRun))
        cleanup.execute(delete(Setting))
        cleanup.execute(delete(ScanResult))
        cleanup.commit()


@pytest.fixture
def client(bt_engine: Engine) -> Iterator[TestClient]:
    yield from make_client(bt_engine, InlineExecutor())


@pytest.fixture
def queued_client(bt_engine: Engine) -> Iterator[TestClient]:
    yield from make_client(bt_engine, NeverExecutor())


def start(client: TestClient, **extra: Any) -> dict[str, Any]:
    response = client.post("/api/backtests", json={**QUICK, **extra})
    assert response.status_code == 202, response.text
    return dict(response.json())


def test_every_backtest_endpoint_needs_a_login(bt_engine: Engine) -> None:
    app = create_app()
    with TestClient(app) as anonymous:
        for method, path in [
            ("post", "/api/backtests"),
            ("get", "/api/backtests"),
            ("get", "/api/backtests/1"),
            ("delete", "/api/backtests/1"),
            ("get", "/api/backtests/1/report"),
            ("post", "/api/backtests/1/preset"),
        ]:
            assert getattr(anonymous, method)(path).status_code == 401, path


def test_a_run_finishes_and_keeps_its_request_summary_and_detail(client: TestClient) -> None:
    created = start(client, name="첫 실행")

    run = client.get(f"/api/backtests/{created['id']}").json()

    assert run["status"] == "done" and run["progress"] == 1.0 and run["error"] is None
    assert run["name"] == "첫 실행"
    assert run["start_date"] < run["end_date"] == "2026-10-16"  # the period actually used
    assert run["bar_length"] == "1d"
    assert run["params"]["cycle"]["max_stocks"] == 6  # the whole request is kept
    assert run["params"]["params"]["sell"]["min_overlap"] == 2  # parameters included
    assert set(run["summary"]) >= {"period", "data", "signal_quality", "cycle", "warnings"}
    assert set(run["detail"]) == {"signal_quality", "cycle"}
    assert "curves" in run["detail"]["cycle"] and "cycles" in run["detail"]["cycle"]


def test_the_list_has_the_newest_first_and_no_tables(client: TestClient) -> None:
    first, second = start(client), start(client, name="둘째")

    runs = client.get("/api/backtests").json()

    assert [r["id"] for r in runs[:2]] == [second["id"], first["id"]]
    assert "detail" not in runs[0] and "params" not in runs[0]
    assert runs[0]["status"] == "done"


def test_a_queued_run_is_reported_as_queued_and_has_no_report_yet(
    queued_client: TestClient,
) -> None:
    created = start(queued_client)

    assert created["status"] == "queued" and created["progress"] == 0.0
    assert queued_client.get(f"/api/backtests/{created['id']}").json()["status"] == "queued"
    assert queued_client.get(f"/api/backtests/{created['id']}/report").status_code == 409


def test_without_parameters_the_current_settings_are_used(
    client: TestClient, bt_engine: Engine
) -> None:
    with sessionmaker(bind=bt_engine)() as session:
        changed = SignalParams.model_validate(
            {
                **SignalParams().model_dump(),
                "rebuy": {**SignalParams().rebuy.model_dump(), "target_gain": 0.02},
            }
        )
        save_signal_params(session, changed)
        session.commit()

    run = client.get(f"/api/backtests/{start(client)['id']}").json()

    assert run["params"]["params"]["rebuy"]["target_gain"] == 0.02


def test_parameters_in_the_request_win_over_the_settings(client: TestClient) -> None:
    custom = SignalParams().model_dump()
    custom["sell"]["min_overlap"] = 3

    run = client.get(f"/api/backtests/{start(client, params=custom)['id']}").json()

    assert run["params"]["params"]["sell"]["min_overlap"] == 3


def test_a_request_that_cannot_run_is_refused(client: TestClient) -> None:
    bad_param = {
        "sensitivity": {"target": "cycle", "x": {"path": "sell.nonsense", "values": [1, 2]}},
    }
    assert client.post("/api/backtests", json={**QUICK, **bad_param}).status_code == 422
    assert (
        client.post(
            "/api/backtests", json={**QUICK, "start_date": "2026-05-01", "end_date": "2026-04-01"}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/backtests", json={"signal_quality": None, "cycle": None}).status_code
        == 422
    )
    assert client.post("/api/backtests", json={**QUICK, "surprise": 1}).status_code == 422


def test_a_run_without_data_fails_with_a_reason_instead_of_crashing() -> None:
    empty = sqlite_engine()
    for client in make_client(empty, InlineExecutor()):
        created = start(client)

        run = client.get(f"/api/backtests/{created['id']}").json()

        assert run["status"] == "failed"
        assert "No daily bars are stored" in run["error"]
        assert run["summary"] == {} or "message" in run["summary"]


def test_the_report_is_markdown_that_describes_the_run(client: TestClient) -> None:
    created = start(client, name="리포트 시험")

    response = client.get(f"/api/backtests/{created['id']}/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    text = response.text
    assert text.startswith("# 백테스트 리포트: 리포트 시험")
    for section in (
        "## 0. 데이터와 가정",
        "## 1. 신호 품질",
        "## 2. 수량 늘리기",
        "슬리피지 민감도",
        "무작위 진입",
        "KOSPI",
    ):
        assert section in text
    assert "6장 기본값을 정하는 일은 하지 않습니다" in text  # it only describes
    assert "수정주가 사용: 예" in text


def test_the_parameters_of_a_run_can_be_kept_as_a_preset(
    client: TestClient, bt_engine: Engine
) -> None:
    custom = SignalParams().model_dump()
    custom["rebuy"]["target_gain"] = 0.015
    created = start(client, params=custom, name="목표이득 1.5%")

    saved = client.post(f"/api/backtests/{created['id']}/preset", json={})

    assert saved.status_code == 201 and saved.json() == {"name": "목표이득 1.5%", "applied": False}
    settings = client.get("/api/settings").json()
    assert [p["name"] for p in settings["presets"]] == ["목표이득 1.5%"]
    assert (
        settings["signal_params"]["rebuy"]["target_gain"] == 0.01
    )  # the current settings are untouched
    with sessionmaker(bind=bt_engine)() as session:
        assert load_signal_params(session).rebuy.target_gain == 0.01


def test_a_run_can_be_applied_so_that_the_screener_uses_its_parameters(
    client: TestClient, bt_engine: Engine
) -> None:
    custom = SignalParams().model_dump()
    custom["screener"]["drawdown_threshold_pct"] = -25.0
    created = start(client, params=custom)

    saved = client.post(
        f"/api/backtests/{created['id']}/preset", json={"name": "적용할 것", "apply": True}
    )

    assert saved.json() == {"name": "적용할 것", "applied": True}
    assert (
        client.get("/api/settings").json()["signal_params"]["screener"]["drawdown_threshold_pct"]
        == -25.0
    )
    # what the scanner reads is what the run used
    with sessionmaker(bind=bt_engine)() as session:
        assert load_signal_params(session).screener.drawdown_threshold_pct == -25.0
    # and the next scan really uses that threshold
    assert client.post("/api/screener/run", json={}).status_code == 200
    gate = client.get("/api/screener/results").json()["gate"]
    assert gate["drawdown_threshold_pct"] == -25.0


def test_a_preset_name_defaults_to_the_run_and_is_checked(client: TestClient) -> None:
    created = start(client)

    assert (
        client.post(f"/api/backtests/{created['id']}/preset", json={}).json()["name"]
        == f"백테스트 #{created['id']}"
    )
    assert (
        client.post(f"/api/backtests/{created['id']}/preset", json={"name": "a/b"}).status_code
        == 422
    )


def test_unknown_runs_are_404_and_a_run_can_be_deleted(client: TestClient) -> None:
    for call in (
        client.get("/api/backtests/9999"),
        client.get("/api/backtests/9999/report"),
        client.post("/api/backtests/9999/preset", json={}),
        client.delete("/api/backtests/9999"),
    ):
        assert call.status_code == 404

    created = start(client)
    assert client.delete(f"/api/backtests/{created['id']}").status_code == 204
    assert client.get(f"/api/backtests/{created['id']}").status_code == 404
