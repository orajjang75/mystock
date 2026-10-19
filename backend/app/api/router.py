from fastapi import APIRouter

from app.api import (
    alerts,
    auth,
    backtests,
    health,
    holdings,
    ops,
    screener,
    settings,
    stocks,
    watchlist,
)

api_router = APIRouter()
api_router.include_router(alerts.router)
api_router.include_router(auth.router)
api_router.include_router(backtests.router)
api_router.include_router(health.router)
api_router.include_router(holdings.router)
api_router.include_router(ops.router)
api_router.include_router(screener.router)
api_router.include_router(settings.router)
api_router.include_router(stocks.router)
api_router.include_router(watchlist.router)
