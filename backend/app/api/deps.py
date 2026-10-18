from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

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
