from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.api.deps import DbSession, require_user
from app.services import watchlist

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(require_user)])


class WatchlistItemOut(BaseModel):
    code: str
    name: str
    market: str
    added_date: date
    scan_date: date | None
    score: float | None
    previous_scan_date: date | None
    previous_score: float | None
    change: float | None


class AddRequest(BaseModel):
    code: str


@router.get("")
def list_items(db: DbSession) -> list[WatchlistItemOut]:
    """Watched stocks with their latest score and the change since the previous scan."""
    return [
        WatchlistItemOut(
            code=item.code,
            name=item.name,
            market=item.market,
            added_date=item.added_date,
            scan_date=item.scan_date,
            score=item.score,
            previous_scan_date=item.previous_scan_date,
            previous_score=item.previous_score,
            change=item.change,
        )
        for item in watchlist.items(db)
    ]


@router.post("")
def add(body: AddRequest, db: DbSession, response: Response) -> dict[str, str]:
    """Watch a stock of the scan universe. 201 when added, 200 if it was already watched."""
    try:
        entry, created = watchlist.add(db, body.code)
    except watchlist.NotInUniverseError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{body.code} is not in the scan universe"
        ) from error
    db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {"code": entry.code}


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def remove(code: str, db: DbSession) -> Response:
    if not watchlist.remove(db, code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{code} is not on the watchlist")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
