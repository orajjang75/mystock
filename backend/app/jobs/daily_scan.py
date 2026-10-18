"""Daily job: collect the day's data, then scan (PRD 8장 일봉 작업, 10장 휴장일 처리).

Runs after the investor-flow data is final (``DAILY_SCAN_TIME``). The scheduler (step 6) only
needs to call ``run_daily_scan``; it skips holidays and early starts by itself.
"""

import argparse
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.adapters.base import MarketDataAdapter
from app.adapters.factory import get_adapter
from app.core.config import get_settings
from app.core.market import KST, is_trading_day, last_confirmed_weekday
from app.db.session import get_sessionmaker
from app.engine.params import SignalParams
from app.jobs.ingest import IngestSummary, run_ingest
from app.services.screener import ScanError, ScanSummary, run_scan
from app.services.universe import UniverseSpec

logger = logging.getLogger(__name__)

TARGET_SECONDS = 600  # PRD 성공 지표: 스캔은 장 마감 후 10분 이내


@dataclass(frozen=True, slots=True)
class DailyScanResult:
    skipped: str | None  # why nothing ran
    scan_date: date | None = None
    ingest: IngestSummary | None = None
    scan: ScanSummary | None = None
    elapsed_seconds: float = 0.0


def run_daily_scan(
    session: Session,
    adapter: MarketDataAdapter,
    *,
    now: datetime | None = None,
    scan_date: date | None = None,
    force: bool = False,
    spec: UniverseSpec | None = None,
    params: SignalParams | None = None,
) -> DailyScanResult:
    """Ingest and scan for ``scan_date`` (default: today). Commits on success.

    Without ``force`` it does nothing on holidays or before ``DAILY_SCAN_TIME``.
    """
    now = (now or datetime.now(KST)).astimezone(KST)
    day = scan_date or now.date()
    if not force:
        if not is_trading_day(day):
            logger.info("daily scan skipped: %s is not a trading day", day)
            return DailyScanResult(skipped="not a trading day", scan_date=day)
        if scan_date is None and now.time() < get_settings().daily_scan_time:
            logger.info("daily scan skipped: before %s", get_settings().daily_scan_time)
            return DailyScanResult(skipped="before the scan time", scan_date=day)

    started = time.monotonic()
    ingest = run_ingest(session, adapter, as_of=day, now=now, spec=spec)
    try:
        scan = run_scan(session, day, params)
    except ScanError as error:
        session.rollback()
        logger.warning("daily scan skipped: %s", error)
        return DailyScanResult(skipped=str(error), scan_date=day, ingest=ingest)
    session.commit()

    elapsed = round(time.monotonic() - started, 2)
    level = logging.INFO if elapsed <= TARGET_SECONDS else logging.WARNING
    logger.log(
        level, "daily scan finished in %.1fs (target %ds): %s", elapsed, TARGET_SECONDS, scan
    )
    return DailyScanResult(None, day, ingest, scan, elapsed)


def main() -> None:
    """``python -m app.jobs.daily_scan [--date YYYY-MM-DD] [--force]``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="scan this day instead of today")
    parser.add_argument("--force", action="store_true", help="ignore holidays and the scan time")
    args = parser.parse_args()
    scan_date = args.date or (last_confirmed_weekday(datetime.now(KST)) if args.force else None)
    with get_sessionmaker()() as session:
        run_daily_scan(
            session,
            get_adapter(),
            scan_date=scan_date,
            force=args.force or args.date is not None,
            spec=UniverseSpec.from_settings(),
        )


if __name__ == "__main__":
    main()
