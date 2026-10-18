"""Collection status: when each market-data source was last fetched successfully.

The scheduler jobs write it, the freshness check and /api/health read it. It lives in its own
``settings`` row so the jobs never overwrite the user's settings.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.secrets import redact
from app.db.models import Setting

ROW = "collection_status"
SOURCES = ("daily", "intraday")
_MAX_ERROR = 300


@dataclass(frozen=True, slots=True)
class SourceStatus:
    last_success: datetime | None = None
    last_attempt: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load_status(session: Session) -> dict[str, SourceStatus]:
    row = session.get(Setting, ROW)
    saved: dict[str, Any] = row.value if row else {}
    return {
        source: SourceStatus(
            last_success=_parse(saved.get(source, {}).get("last_success")),
            last_attempt=_parse(saved.get(source, {}).get("last_attempt")),
            last_error=saved.get(source, {}).get("last_error"),
            consecutive_failures=int(saved.get(source, {}).get("consecutive_failures", 0)),
        )
        for source in SOURCES
    }


def _write(session: Session, source: str, entry: dict[str, Any]) -> None:
    row = session.get(Setting, ROW)
    value = {**(row.value if row else {}), source: entry}
    if row is None:
        session.add(Setting(name=ROW, value=value))
    else:
        row.value = value
    session.flush()


def record_success(session: Session, source: str, at: datetime) -> None:
    """A fetch of ``source`` succeeded at ``at``. Does not commit."""
    _write(
        session,
        source,
        {
            "last_success": at.isoformat(),
            "last_attempt": at.isoformat(),
            "last_error": None,
            "consecutive_failures": 0,
        },
    )


def record_failure(session: Session, source: str, at: datetime, error: str) -> None:
    """A fetch of ``source`` failed at ``at``. The message is stored with secrets masked."""
    before = load_status(session)[source]
    _write(
        session,
        source,
        {
            "last_success": before.last_success.isoformat() if before.last_success else None,
            "last_attempt": at.isoformat(),
            "last_error": redact(error)[:_MAX_ERROR],
            "consecutive_failures": before.consecutive_failures + 1,
        },
    )
