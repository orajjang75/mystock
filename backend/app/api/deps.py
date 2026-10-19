from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.market import KST
from app.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]


def require_user(request: Request) -> str:
    """Return the logged-in username, or 401. Add as a dependency to every non-public route."""
    user = request.session.get("user")
    if not isinstance(user, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[str, Depends(require_user)]


def current_time() -> datetime:
    """Now in KST. A dependency so that tests can move the clock."""
    return datetime.now(KST)


Now = Annotated[datetime, Depends(current_time)]


def reject_in_paper_run() -> None:
    """모의 운영 (PAPER_RUN=true): signals and alerts only. Recording a trade changes a holding's
    state, which is exactly what a read-only run must not do."""
    if get_settings().paper_run:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "모의 운영 중에는 체결을 기록하지 않습니다 (PAPER_RUN=true). 신호와 알림만 확인합니다.",
        )
