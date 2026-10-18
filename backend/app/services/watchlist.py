"""Watchlist (S-11): scan-universe stocks only, shown with their latest score and its change."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, ScanResult, Watchlist


class NotInUniverseError(ValueError):
    """The stock is not part of the current scan universe."""


@dataclass(frozen=True, slots=True)
class WatchlistItem:
    code: str
    name: str
    market: str
    added_date: date
    scan_date: date | None  # the latest scan
    score: float | None  # None: not scored in the latest scan (failed the gate)
    previous_scan_date: date | None
    previous_score: float | None
    change: float | None  # score - previous_score when both exist


def add(session: Session, code: str) -> tuple[Watchlist, bool]:
    """Add ``code``; returns (entry, created). Only scan-universe stocks are allowed."""
    instrument = session.get(Instrument, code)
    if instrument is None or instrument.market_cap_rank is None:
        raise NotInUniverseError(code)
    existing = session.get(Watchlist, code)
    if existing is not None:
        return existing, False
    entry = Watchlist(code=code)
    session.add(entry)
    session.flush()
    session.refresh(entry)
    return entry, True


def remove(session: Session, code: str) -> bool:
    entry = session.get(Watchlist, code)
    if entry is None:
        return False
    session.delete(entry)
    session.flush()
    return True


def items(session: Session) -> list[WatchlistItem]:
    """Watchlist with each stock's score in the latest scan and the one before it."""
    dates = list(
        session.scalars(
            select(ScanResult.scan_date).distinct().order_by(ScanResult.scan_date.desc()).limit(2)
        )
    )
    latest = dates[0] if dates else None
    previous = dates[1] if len(dates) > 1 else None
    scores: dict[tuple[date, str], float] = {}
    if dates:
        scores = {
            (day, code): float(score)
            for day, code, score in session.execute(
                select(ScanResult.scan_date, ScanResult.code, ScanResult.score).where(
                    ScanResult.scan_date.in_(dates)
                )
            )
        }
    rows = session.execute(
        select(Watchlist, Instrument)
        .join(Instrument, Instrument.code == Watchlist.code)
        .order_by(Watchlist.added_date, Watchlist.code)
    ).all()
    result = []
    for entry, instrument in rows:
        score = scores.get((latest, entry.code)) if latest else None
        before = scores.get((previous, entry.code)) if previous else None
        result.append(
            WatchlistItem(
                code=entry.code,
                name=instrument.name,
                market=instrument.market.value,
                added_date=entry.added_date,
                scan_date=latest,
                score=score,
                previous_scan_date=previous,
                previous_score=before,
                change=round(score - before, 2)
                if score is not None and before is not None
                else None,
            )
        )
    result.sort(key=lambda item: (item.score is None, -(item.score or 0.0), item.code))
    return result
