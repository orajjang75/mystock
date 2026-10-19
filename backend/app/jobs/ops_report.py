"""``python -m app.jobs.ops_report``: the 모의 운영 report for the last days, as Markdown.

    python -m app.jobs.ops_report --days 7            # printed
    python -m app.jobs.ops_report --from 2026-11-02 --to 2026-11-27 --save

``--save`` writes docs/ops-reports/<from>_<to>.md. Run it daily (cron) during a paper run: the
gate of roadmap step 5 is read from the table at the top.
"""

import argparse
from datetime import date, datetime, timedelta

from app.core.config import REPO_ROOT
from app.core.market import KST
from app.db.session import get_sessionmaker
from app.services import ops


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="the last N days up to --to")
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat, help="default: today")
    parser.add_argument(
        "--save", action="store_true", help="write docs/ops-reports/ instead of printing"
    )
    args = parser.parse_args(argv)
    last = args.last or datetime.now(KST).date()
    first = args.first or last - timedelta(days=args.days - 1)
    with get_sessionmaker()() as session:
        text = ops.render_markdown(ops.period_report(session, first, last))
    if not args.save:
        print(text)
        return 0
    folder = REPO_ROOT / "docs" / "ops-reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{first}_{last}.md"
    path.write_text(text, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
