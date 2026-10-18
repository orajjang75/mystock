import logging
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.adapters.factory import get_adapter
from app.api.holdings import register_error_handlers
from app.api.router import api_router
from app.core.config import get_settings
from app.core.secrets import install_log_redaction
from app.db.session import get_sessionmaker
from app.jobs.monitor import JobContext
from app.jobs.scheduler import build_scheduler
from app.services.backtests import fail_interrupted

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the scheduler with the app when SCHEDULER_ENABLED is set (one worker only)."""
    settings = get_settings()
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    install_log_redaction(settings)
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = build_scheduler(JobContext(get_sessionmaker(), get_adapter(settings), settings))
        scheduler.start()
        logger.info("scheduler started: %s", [job.id for job in scheduler.get_jobs()])
    app.state.scheduler = scheduler
    try:
        with get_sessionmaker()() as session:
            if stuck := fail_interrupted(session):
                logger.warning("%d backtest runs were interrupted by the last stop", stuck)
    except Exception:  # the database may not be ready; the API reports that itself
        logger.warning("could not check for interrupted backtests", exc_info=True)
    # One backtest at a time: they are CPU-heavy and share the data they load.
    app.state.backtest_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backtest")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        app.state.backtest_executor.shutdown(wait=False, cancel_futures=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="mystock",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key.get_secret_value(),
        session_cookie="mystock_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.include_router(api_router, prefix="/api")
    register_error_handlers(app)
    return app
