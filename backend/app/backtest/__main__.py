"""``python -m app.backtest``: run a backtest from the terminal and print its report.

For working on real data without the browser: the stored bars and universe snapshots are used as
they are, and the report is written next to the PRD (docs/backtest-reports/) unless ``--stdout``.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from app.backtest.config import BacktestConfig
from app.backtest.report import build_report
from app.backtest.runner import run_backtest
from app.core.config import REPO_ROOT
from app.db.session import get_sessionmaker
from app.services.settings import load_signal_params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="JSON file with a BacktestConfig (default: all defaults)"
    )
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--bar", choices=["30m", "60m", "1d"], help="signal bars of the cycle run")
    parser.add_argument("--survivors-only", action="store_true", help="leave delisted stocks out")
    parser.add_argument(
        "--fixed-universe", action="store_true", help="today's ranking for every day"
    )
    parser.add_argument(
        "--stdout", action="store_true", help="print the report instead of saving it"
    )
    args = parser.parse_args(argv)

    raw = json.loads(args.config.read_text()) if args.config else {}
    with get_sessionmaker()() as session:
        if "params" not in raw:
            raw["params"] = load_signal_params(session).model_dump(mode="json")
        if args.start:
            raw["start_date"] = args.start.isoformat()
        if args.end:
            raw["end_date"] = args.end.isoformat()
        if args.bar:
            raw["bar_length"] = args.bar
        raw.setdefault("universe", {})
        if args.survivors_only:
            raw["universe"]["include_delisted"] = False
        if args.fixed_universe:
            raw["universe"]["point_in_time"] = False
        config = BacktestConfig.model_validate(raw)

        def progress(fraction: float, message: str) -> None:
            print(f"[{fraction:5.0%}] {message}", file=sys.stderr)

        summary, detail = run_backtest(session, config, progress)

    text = build_report(config.name, config.model_dump(mode="json"), summary, detail)
    if args.stdout:
        print(text)
        return 0
    folder = REPO_ROOT / "docs" / "backtest-reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
