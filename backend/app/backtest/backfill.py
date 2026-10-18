"""``python -m app.backtest.backfill``: store the universe of past dates (universe_snapshots).

The daily scan stores one snapshot per run from now on. For the history before that, the adapter
is asked who was big on each past date. Run ``make ingest`` afterwards so the bars of stocks that
were members then (and may be delisted since) are collected too.
"""

import argparse
from datetime import date, datetime, timedelta

from app.adapters.factory import get_adapter
from app.backtest.dataset import backfill_snapshots
from app.core.market import KST, last_confirmed_weekday
from app.db.session import get_sessionmaker
from app.services.universe import UniverseSpec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, help="default: 400 days before --end")
    parser.add_argument("--end", type=date.fromisoformat, help="default: the last confirmed day")
    parser.add_argument("--step-days", type=int, default=30, help="calendar days between snapshots")
    args = parser.parse_args(argv)
    end = args.end or last_confirmed_weekday(datetime.now(KST))
    start = args.start or end - timedelta(days=400)
    with get_sessionmaker()() as session:
        stored = backfill_snapshots(
            session,
            get_adapter(),
            start,
            end,
            step_days=args.step_days,
            spec=UniverseSpec.from_settings(),
        )
    print(f"stored {len(stored)} snapshots: {stored[0]} .. {stored[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
