from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.base import Base

_CHUNK = 5000


def upsert(
    session: Session,
    model: type[Base],
    rows: Sequence[Mapping[str, Any]],
    *,
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
    touch_updated_at: bool = False,
) -> int:
    """INSERT ... ON CONFLICT DO UPDATE on PostgreSQL (production) or SQLite (unit tests).

    Does not commit. ``touch_updated_at`` stamps ``updated_at`` on every written row, which is
    what /api/health reports as the last quote update.
    """
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    insert = {"postgresql": postgresql_insert, "sqlite": sqlite_insert}[dialect]
    statement: Any = insert(model)
    changes: dict[str, Any] = {column: statement.excluded[column] for column in update_columns}
    if touch_updated_at:
        changes["updated_at"] = func.now()
    statement = statement.on_conflict_do_update(index_elements=list(conflict_columns), set_=changes)
    for start in range(0, len(rows), _CHUNK):
        session.execute(statement, list(rows[start : start + _CHUNK]))
    return len(rows)
