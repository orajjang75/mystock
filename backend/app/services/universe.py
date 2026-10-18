"""Scan universe (S-1): KOSPI top 100 + KOSDAQ top 20 by market cap, after safety filters.

Interpretation of S-1: the exclusions are applied *before* taking the top N, so excluded stocks
are replaced by the next-largest eligible ones and the universe is exactly 100 + 20 whenever
enough eligible stocks exist. If fewer exist, the universe is smaller and a warning is logged.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.adapters.base import Listing, MarketDataAdapter
from app.core.config import get_settings
from app.db.enums import Market
from app.db.models import Instrument, UniverseSnapshot
from app.db.upsert import upsert
from app.engine.params import DEFAULT_PARAMS
from app.engine.screener_signals import liquidity_ok

logger = logging.getLogger(__name__)

# Calendar days of daily bars to request so that 20 trading days are covered across holidays.
_LIQUIDITY_LOOKBACK_DAYS = 50


@dataclass(frozen=True, slots=True)
class UniverseSpec:
    kospi_top: int = 100
    kosdaq_top: int = 20
    min_avg_trading_value: int = DEFAULT_PARAMS.screener.min_avg_trading_value
    liquidity_window: int = DEFAULT_PARAMS.screener.liquidity_window
    include_preferred: bool = False
    # Ask the adapter for this many times N stocks per market before filtering.
    pool_factor: int = 2

    @classmethod
    def from_settings(cls) -> "UniverseSpec":
        return cls(include_preferred=get_settings().universe_include_preferred)

    def top(self, market: Market) -> int:
        return self.kospi_top if market is Market.KOSPI else self.kosdaq_top


@dataclass(frozen=True, slots=True)
class UniverseMember:
    code: str
    market: Market
    rank: int  # 1-based market-cap rank within the universe of its market


def _passes_flags(listing: Listing, spec: UniverseSpec) -> bool:
    if listing.is_admin_issue or listing.is_halted or listing.is_warning:
        return False
    return spec.include_preferred or not listing.is_preferred


def _liquidity_check(
    adapter: MarketDataAdapter, as_of: date, spec: UniverseSpec
) -> Callable[[Sequence[str]], set[str]]:
    def check(codes: Sequence[str]) -> set[str]:
        passed: set[str] = set()
        for code in codes:
            bars = adapter.fetch_daily_ohlcv(
                code, as_of - timedelta(days=_LIQUIDITY_LOOKBACK_DAYS), as_of
            )
            ok = liquidity_ok(
                bars["trading_value"], spec.min_avg_trading_value, spec.liquidity_window
            )
            if not ok.empty and bool(ok.iloc[-1]):
                passed.add(code)
        return passed

    return check


def _take_top(
    ranked: Sequence[Listing], n: int, check: Callable[[Sequence[str]], set[str]]
) -> list[Listing]:
    """Walk down the ranking, checking liquidity only for as many stocks as are still needed."""
    selected: list[Listing] = []
    position = 0
    while len(selected) < n and position < len(ranked):
        batch = ranked[position : position + n - len(selected)]
        position += len(batch)
        passed = check([listing.code for listing in batch])
        selected.extend(listing for listing in batch if listing.code in passed)
    return selected


def build_universe(
    session: Session,
    adapter: MarketDataAdapter,
    as_of: date,
    spec: UniverseSpec | None = None,
) -> list[UniverseMember]:
    """Re-rank by market cap as of ``as_of``, filter, and save the result to ``instruments``.

    ``instruments.market_cap_rank`` is set to 1..N for universe members and NULL for everyone
    else. Flushes but does not commit.
    """
    spec = spec or UniverseSpec.from_settings()
    check = _liquidity_check(adapter, as_of, spec)

    members: list[UniverseMember] = []
    listings: list[Listing] = []
    for market in (Market.KOSPI, Market.KOSDAQ):
        n = spec.top(market)
        pool = adapter.fetch_listings(as_of, limit_per_market=n * spec.pool_factor)
        pool = [listing for listing in pool if listing.market is market]
        listings.extend(pool)
        eligible = sorted(
            (listing for listing in pool if _passes_flags(listing, spec)),
            key=lambda listing: (-listing.market_cap, listing.code),
        )
        chosen = _take_top(eligible, n, check)
        if len(chosen) < n:
            logger.warning("%s universe has only %d of %d stocks", market.value, len(chosen), n)
        members.extend(
            UniverseMember(listing.code, market, rank) for rank, listing in enumerate(chosen, 1)
        )

    _save(session, listings, members)
    save_snapshot(session, as_of, listings, members)
    return members


def _save(session: Session, listings: Sequence[Listing], members: Sequence[UniverseMember]) -> None:
    rank_by_code = {member.code: member.rank for member in members}
    session.execute(update(Instrument).values(market_cap_rank=None))
    upsert(
        session,
        Instrument,
        [
            {
                "code": listing.code,
                "name": listing.name,
                "market": listing.market,
                "market_cap_rank": rank_by_code.get(listing.code),
                "is_preferred": listing.is_preferred,
                "is_admin_issue": listing.is_admin_issue,
                "is_halted": listing.is_halted,
                "is_warning": listing.is_warning,
            }
            for listing in listings
        ],
        conflict_columns=["code"],
        update_columns=[
            "name",
            "market",
            "market_cap_rank",
            "is_preferred",
            "is_admin_issue",
            "is_halted",
            "is_warning",
        ],
    )
    session.flush()


def save_snapshot(
    session: Session,
    as_of: date,
    listings: Sequence[Listing],
    members: Sequence[UniverseMember],
) -> None:
    """Remember who was in the universe on ``as_of`` and with which rank and market cap.

    The backtest builds its universe from these rows, so a stock that is big today is not
    assumed to have been big years ago (PRD 10장 데이터: 과거 시점 시가총액 순위). Re-running a
    date replaces it. Flushes but does not commit.
    """
    cap = {listing.code: listing.market_cap for listing in listings}
    session.execute(delete(UniverseSnapshot).where(UniverseSnapshot.as_of == as_of))
    session.add_all(
        UniverseSnapshot(
            as_of=as_of,
            code=member.code,
            market=member.market,
            rank=member.rank,
            market_cap=cap[member.code],
        )
        for member in members
    )
    session.flush()


def snapshot_universe(
    session: Session,
    adapter: MarketDataAdapter,
    as_of: date,
    spec: UniverseSpec | None = None,
) -> list[UniverseMember]:
    """Rank the universe as of a (past) date and store only the snapshot.

    Unlike ``build_universe`` this leaves ``instruments.market_cap_rank`` (today's universe)
    alone, so a backfill of past dates never changes what the scanner scans. Stocks that are not
    in ``instruments`` yet (delisted since) are added to it, because the snapshot refers to them.
    Flushes but does not commit.
    """
    spec = spec or UniverseSpec.from_settings()
    check = _liquidity_check(adapter, as_of, spec)
    members: list[UniverseMember] = []
    listings: list[Listing] = []
    for market in (Market.KOSPI, Market.KOSDAQ):
        n = spec.top(market)
        pool = [
            listing
            for listing in adapter.fetch_listings(as_of, limit_per_market=n * spec.pool_factor)
            if listing.market is market
        ]
        listings.extend(pool)
        eligible = sorted(
            (listing for listing in pool if _passes_flags(listing, spec)),
            key=lambda listing: (-listing.market_cap, listing.code),
        )
        chosen = _take_top(eligible, n, check)
        members.extend(
            UniverseMember(listing.code, market, rank) for rank, listing in enumerate(chosen, 1)
        )
    known = set(session.scalars(select(Instrument.code)))
    missing = [listing for listing in listings if listing.code not in known]
    upsert(
        session,
        Instrument,
        [
            {
                "code": listing.code,
                "name": listing.name,
                "market": listing.market,
                "market_cap_rank": None,
                "is_preferred": listing.is_preferred,
                "is_admin_issue": listing.is_admin_issue,
                "is_halted": listing.is_halted,
                "is_warning": listing.is_warning,
            }
            for listing in missing
        ],
        conflict_columns=["code"],
        update_columns=["name"],
    )
    save_snapshot(session, as_of, listings, members)
    return members


def load_universe(session: Session) -> list[UniverseMember]:
    """The universe as last saved by ``build_universe``."""
    rows = session.execute(
        select(Instrument.code, Instrument.market, Instrument.market_cap_rank)
        .where(Instrument.market_cap_rank.is_not(None))
        .order_by(Instrument.market, Instrument.market_cap_rank)
    )
    return [UniverseMember(code, market, rank) for code, market, rank in rows if rank is not None]


__all__ = [
    "UniverseMember",
    "UniverseSpec",
    "build_universe",
    "load_universe",
    "save_snapshot",
    "snapshot_universe",
]
