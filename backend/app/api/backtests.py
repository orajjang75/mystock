from concurrent.futures import Executor
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, require_user
from app.backtest.config import BacktestConfig
from app.db.models import BacktestRun
from app.db.session import get_sessionmaker
from app.engine.params import SignalParams
from app.services import backtests as service
from app.services import settings as settings_service

router = APIRouter(prefix="/backtests", tags=["backtests"], dependencies=[Depends(require_user)])


def get_executor(request: Request) -> Executor:
    """The worker that runs backtests (tests replace it with one that runs them inline)."""
    executor: Executor = request.app.state.backtest_executor
    return executor


def get_factory() -> service.SessionFactory:
    return get_sessionmaker()


Worker = Annotated[Executor, Depends(get_executor)]
Factory = Annotated[service.SessionFactory, Depends(get_factory)]


class BacktestRequest(BacktestConfig):
    """The config of a run. Without ``params`` the current settings are used."""

    params: SignalParams | None = None  # type: ignore[assignment]


class RunSummaryOut(BaseModel):
    id: int
    name: str | None
    status: str  # queued | running | done | failed
    progress: float
    executed_at: datetime
    start_date: date
    end_date: date
    bar_length: str
    summary: dict[str, Any]
    error: str | None


class RunOut(RunSummaryOut):
    params: dict[str, Any]  # the whole request, parameters included
    detail: dict[str, Any]  # tables and curves


class PresetRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[^/\\]+$")] | None = None
    apply: bool = False  # also make it the current settings (what the screener reads)


class PresetResult(BaseModel):
    name: str
    applied: bool


def _summary_out(run: BacktestRun) -> RunSummaryOut:
    return RunSummaryOut(
        id=run.id,
        name=run.name,
        status=run.status,
        progress=run.progress,
        executed_at=run.executed_at,
        start_date=run.start_date,
        end_date=run.end_date,
        bar_length=run.bar_length.value,
        summary=run.summary,
        error=run.error,
    )


def _out(run: BacktestRun) -> RunOut:
    return RunOut(**_summary_out(run).model_dump(), params=run.params, detail=run.detail)


def _run(db: DbSession, run_id: int) -> BacktestRun:
    try:
        return service.get_run(db, run_id)
    except service.RunNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown backtest {run_id}") from None


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create(body: BacktestRequest, db: DbSession, worker: Worker, factory: Factory) -> RunSummaryOut:
    """Queue a backtest. It runs in the background: poll ``GET /backtests/{id}``."""
    data = body.model_dump()
    if body.params is None:
        data["params"] = settings_service.load_signal_params(db)
    config = BacktestConfig.model_validate(data)
    run = service.create_run(db, config)
    service.submit(worker, factory, run.id)
    db.refresh(run)
    return _summary_out(run)


@router.get("")
def list_runs(db: DbSession) -> list[RunSummaryOut]:
    """The latest runs, newest first, without their tables."""
    return [_summary_out(r) for r in service.list_runs(db)]


@router.get("/{run_id}")
def get_run(run_id: int, db: DbSession) -> RunOut:
    return _out(_run(db, run_id))


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: int, db: DbSession) -> Response:
    _run(db, run_id)
    service.delete_run(db, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}/report")
def report(run_id: int, db: DbSession) -> Response:
    """The run as a Markdown report (what was compared, how big the samples are, what failed)."""
    run = _run(db, run_id)
    try:
        text = service.report_for(run)
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    return Response(text, media_type="text/markdown; charset=utf-8")


@router.post("/{run_id}/preset", status_code=status.HTTP_201_CREATED)
def save_preset(run_id: int, body: PresetRequest, db: DbSession) -> PresetResult:
    """Save the parameters of this run as a preset; with ``apply`` the screener uses them next."""
    run = _run(db, run_id)
    name = (body.name or service.default_preset_name(run)).strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The name is empty")
    service.save_as_preset(db, run, name, apply=body.apply)
    return PresetResult(name=name, applied=body.apply)
