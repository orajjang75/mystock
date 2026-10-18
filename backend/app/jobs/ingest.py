"""Collection jobs: pull confirmed bars from the adapter and upsert them (PRD 8장 일봉·분봉 작업).

Only confirmed bars are stored (CLAUDE.md 규칙 4): a daily bar after the session close, a
30-minute bar after its end time. Re-running a job rewrites the same rows (idempotent).
The ``ingest_*`` functions flush but do not commit; ``run_ingest`` commits once at the end.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import (
    DAILY_COLUMNS,
    FLOW_COLUMNS,
    INDEX_COLUMNS,
    INTRADAY_COLUMNS,
    MarketDataAdapter,
)
from app.adapters.factory import get_adapter
from app.core.market import (
    INTRADAY_BAR_MINUTES,
    KST,
    is_daily_bar_confirmed,
    is_intraday_bar_confirmed,
    last_confirmed_weekday,
)
from app.db.enums import BarLength
from app.db.models import (
    Holding,
    IndexDaily,
    InvestorFlowDaily,
    OhlcvDaily,
    OhlcvIntraday,
    UniverseSnapshot,
)
from app.db.session import get_sessionmaker
from app.db.upsert import upsert
from app.services.universe import UniverseSpec, build_universe

logger = logging.getLogger(__name__)


def _records(
    frame: pd.DataFrame, columns: Sequence[str], key_column: str, key_of: Callable[[Any], Any]
) -> list[dict[str, Any]]:
    keys = [key_of(ts) for ts in frame.index]
    records = [{str(k): v for k, v in r.items()} for r in frame[list(columns)].to_dict("records")]
    for key, record in zip(keys, records, strict=True):
        record[key_column] = key
    return records


def _confirmed_daily(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    mask = [is_daily_bar_confirmed(ts.date(), now) for ts in frame.index]
    return frame.loc[mask]


def ingest_daily(
    session: Session,
    adapter: MarketDataAdapter,
    codes: Sequence[str],
    *,
    start: date,
    end: date,
    now: datetime,
) -> int:
    written = 0
    for code in codes:
        frame = _confirmed_daily(adapter.fetch_daily_ohlcv(code, start, end), now)
        rows = _records(frame, DAILY_COLUMNS, "trade_date", lambda ts: ts.date())
        for row in rows:
            row["code"] = code
        written += upsert(
            session,
            OhlcvDaily,
            rows,
            conflict_columns=["code", "trade_date"],
            update_columns=DAILY_COLUMNS,
            touch_updated_at=True,
        )
    return written


def ingest_investor_flow(
    session: Session,
    adapter: MarketDataAdapter,
    codes: Sequence[str],
    *,
    start: date,
    end: date,
    now: datetime,
) -> int:
    # The time KRX finalizes investor data is an open issue (PRD 10장); until it is decided the
    # same session-close rule as for daily bars applies.
    written = 0
    for code in codes:
        frame = _confirmed_daily(adapter.fetch_investor_flow(code, start, end), now)
        rows = _records(frame, FLOW_COLUMNS, "trade_date", lambda ts: ts.date())
        for row in rows:
            row["code"] = code
        written += upsert(
            session,
            InvestorFlowDaily,
            rows,
            conflict_columns=["code", "trade_date"],
            update_columns=FLOW_COLUMNS,
            touch_updated_at=True,
        )
    return written


def ingest_intraday_30m(
    session: Session,
    adapter: MarketDataAdapter,
    codes: Sequence[str],
    *,
    start: date,
    end: date,
    now: datetime,
) -> int:
    written = 0
    for code in codes:
        frame = adapter.fetch_intraday_30m(code, start, end)
        mask = [
            is_intraday_bar_confirmed(ts.to_pydatetime(), now, INTRADAY_BAR_MINUTES)
            for ts in frame.index
        ]
        rows = _records(
            frame.loc[mask], INTRADAY_COLUMNS, "bar_time", lambda ts: ts.to_pydatetime()
        )
        for row in rows:
            row["code"] = code
            row["bar_length"] = BarLength.M30
        written += upsert(
            session,
            OhlcvIntraday,
            rows,
            conflict_columns=["code", "bar_length", "bar_time"],
            update_columns=INTRADAY_COLUMNS,
            touch_updated_at=True,
        )
    return written


def ingest_index_daily(
    session: Session,
    adapter: MarketDataAdapter,
    *,
    start: date,
    end: date,
    now: datetime,
    index_code: str = "KOSPI",
) -> int:
    frame = _confirmed_daily(adapter.fetch_index_daily(index_code, start, end), now)
    rows = _records(frame, INDEX_COLUMNS, "trade_date", lambda ts: ts.date())
    for row in rows:
        row["index_code"] = index_code
    return upsert(
        session,
        IndexDaily,
        rows,
        conflict_columns=["index_code", "trade_date"],
        update_columns=INDEX_COLUMNS,
        touch_updated_at=True,
    )


def _ingest_history(
    session: Session,
    adapter: MarketDataAdapter,
    codes: Sequence[str],
    start: date,
    end: date,
    now: datetime,
) -> int:
    """Daily bars and flow of past universe members. A stock the source no longer knows is
    skipped with a warning: one delisted name must not stop the whole collection."""
    written = 0
    for code in codes:
        try:
            written += ingest_daily(session, adapter, [code], start=start, end=end, now=now)
            ingest_investor_flow(session, adapter, [code], start=start, end=end, now=now)
        except Exception as error:
            logger.warning(
                "no history for past member %s: %s: %s", code, type(error).__name__, error
            )
    return written


@dataclass(frozen=True, slots=True)
class IngestSummary:
    universe: int
    daily: int
    investor_flow: int
    intraday: int
    index_daily: int


def run_ingest(
    session: Session,
    adapter: MarketDataAdapter,
    *,
    as_of: date,
    now: datetime | None = None,
    spec: UniverseSpec | None = None,
    intraday_codes: Sequence[str] | None = None,
    daily_lookback_days: int = 760,  # ~500 trading days
    intraday_lookback_days: int = 100,  # ~60 trading days
) -> IngestSummary:
    """Rebuild the universe as of ``as_of`` and collect all its market data, then commit.

    Stocks the user holds are collected too, even outside the universe, so their alerts always
    have data. ``intraday_codes`` defaults to the universe plus the holdings.
    """
    now = now or datetime.now(KST)
    started = time.monotonic()
    members = build_universe(session, adapter, as_of, spec)
    universe_codes = [member.code for member in members]
    held = [c for c in session.scalars(select(Holding.code).distinct()) if c not in universe_codes]
    codes = [*universe_codes, *held]

    daily_start = as_of - timedelta(days=daily_lookback_days)
    # Stocks that were in an earlier universe (and may be delisted by now) keep their daily
    # history too: the backtest needs them to avoid survivorship bias.
    history = [
        c
        for c in session.scalars(
            select(UniverseSnapshot.code).where(UniverseSnapshot.as_of >= daily_start).distinct()
        )
        if c not in codes
    ]
    summary = IngestSummary(
        universe=len(universe_codes),
        daily=ingest_daily(session, adapter, codes, start=daily_start, end=as_of, now=now)
        + _ingest_history(session, adapter, history, daily_start, as_of, now),
        investor_flow=ingest_investor_flow(
            session, adapter, codes, start=daily_start, end=as_of, now=now
        ),
        intraday=ingest_intraday_30m(
            session,
            adapter,
            codes if intraday_codes is None else intraday_codes,
            start=as_of - timedelta(days=intraday_lookback_days),
            end=as_of,
            now=now,
        ),
        index_daily=ingest_index_daily(session, adapter, start=daily_start, end=as_of, now=now),
    )
    session.commit()
    logger.info("ingest finished in %.1fs: %s", time.monotonic() - started, summary)
    return summary


def main() -> None:
    """``python -m app.jobs.ingest``: collect everything up to the last confirmed trading day."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    now = datetime.now(KST)
    with get_sessionmaker()() as session:
        run_ingest(
            session,
            get_adapter(),
            as_of=last_confirmed_weekday(now),
            now=now,
            spec=UniverseSpec.from_settings(),
        )


if __name__ == "__main__":
    main()
