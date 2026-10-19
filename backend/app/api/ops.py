from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import DbSession, Now, require_user
from app.services import ops

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_user)])

MAX_DAYS = 62


@router.get("/report")
def report(
    db: DbSession,
    now: Now,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    format: Annotated[str, Query(pattern="^(json|md)$")] = "json",
) -> Any:
    """The 모의 운영 report: bar closes seen, collection failures and alert latency per day.

    Default: the last 7 days up to today. ``format=md`` returns the same as Markdown.
    """
    last = end or now.date()
    first = start or last - timedelta(days=6)
    if first > last:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "from is after to")
    if (last - first).days + 1 > MAX_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"at most {MAX_DAYS} days")
    data = ops.period_report(db, first, last)
    if format == "md":
        return Response(ops.render_markdown(data), media_type="text/markdown; charset=utf-8")
    return data
