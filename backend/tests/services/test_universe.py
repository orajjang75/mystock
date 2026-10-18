import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.mock import MockAdapter
from app.db.enums import Market
from app.db.models import Instrument
from app.services.universe import UniverseSpec, build_universe, load_universe
from tests.conftest import END_DATE


def expected_codes(adapter: MockAdapter, market: Market, n: int, *, preferred: bool) -> list[str]:
    """Independent re-derivation of S-1 from the mock's own flags."""
    listings = [item for item in adapter.fetch_listings(END_DATE) if item.market is market]
    excluded = {
        s.code
        for s in adapter.stocks
        if s.is_admin_issue
        or s.is_halted
        or s.is_warning
        or s.is_illiquid
        or (s.is_preferred and not preferred)
    }
    ranked = sorted(listings, key=lambda item: (-item.market_cap, item.code))
    return [item.code for item in ranked if item.code not in excluded][:n]


def codes(members: list, market: Market) -> list[str]:  # type: ignore[type-arg]
    return [m.code for m in members if m.market is market]


def test_universe_is_exactly_kospi_100_and_kosdaq_20(
    session: Session, mock_adapter: MockAdapter
) -> None:
    members = build_universe(session, mock_adapter, END_DATE, UniverseSpec())

    assert len(codes(members, Market.KOSPI)) == 100
    assert len(codes(members, Market.KOSDAQ)) == 20
    assert len(members) == len({m.code for m in members}) == 120


def test_excluded_stocks_are_replaced_by_the_next_largest(
    session: Session, mock_adapter: MockAdapter
) -> None:
    members = build_universe(session, mock_adapter, END_DATE, UniverseSpec())

    assert codes(members, Market.KOSPI) == expected_codes(
        mock_adapter, Market.KOSPI, 100, preferred=False
    )
    assert codes(members, Market.KOSDAQ) == expected_codes(
        mock_adapter, Market.KOSDAQ, 20, preferred=False
    )
    chosen = {m.code for m in members}
    for stock in mock_adapter.stocks:
        flagged = stock.is_admin_issue or stock.is_halted or stock.is_warning
        assert not (flagged and stock.code in chosen), stock.code
        assert not (stock.is_illiquid and stock.code in chosen), stock.code
        assert not (stock.is_preferred and stock.code in chosen), stock.code


def test_ranks_follow_market_cap_within_each_market(
    session: Session, mock_adapter: MockAdapter
) -> None:
    members = build_universe(session, mock_adapter, END_DATE, UniverseSpec())
    cap = {item.code: item.market_cap for item in mock_adapter.fetch_listings(END_DATE)}

    for market, n in ((Market.KOSPI, 100), (Market.KOSDAQ, 20)):
        ranked = [m for m in members if m.market is market]
        assert [m.rank for m in ranked] == list(range(1, n + 1))
        caps = [cap[m.code] for m in ranked]
        assert caps == sorted(caps, reverse=True)


def test_preferred_shares_are_included_only_when_enabled(
    session: Session, mock_adapter: MockAdapter
) -> None:
    preferred = {s.code for s in mock_adapter.stocks if s.is_preferred}

    without = build_universe(session, mock_adapter, END_DATE, UniverseSpec())
    with_preferred = build_universe(
        session, mock_adapter, END_DATE, UniverseSpec(include_preferred=True)
    )

    assert not preferred & {m.code for m in without}
    assert preferred & {m.code for m in with_preferred}
    assert len(codes(with_preferred, Market.KOSPI)) == 100
    assert codes(with_preferred, Market.KOSPI) == expected_codes(
        mock_adapter, Market.KOSPI, 100, preferred=True
    )


def test_preferred_default_comes_from_the_environment_setting(
    session: Session, mock_adapter: MockAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    assert UniverseSpec.from_settings().include_preferred is False
    monkeypatch.setenv("UNIVERSE_INCLUDE_PREFERRED", "true")
    get_settings.cache_clear()
    try:
        assert UniverseSpec.from_settings().include_preferred is True
    finally:
        get_settings.cache_clear()


def test_universe_is_saved_to_instruments(session: Session, mock_adapter: MockAdapter) -> None:
    members = build_universe(session, mock_adapter, END_DATE, UniverseSpec())
    session.commit()

    assert session.scalar(select(func.count()).select_from(Instrument)) == 150
    assert (
        session.scalar(select(func.count()).where(Instrument.market_cap_rank.is_not(None))) == 120
    )
    assert load_universe(session) == sorted(members, key=lambda m: (m.market.value, m.rank))
    flagged = session.scalars(select(Instrument).where(Instrument.is_admin_issue)).all()
    assert flagged
    assert all(row.market_cap_rank is None for row in flagged)


def test_rebuilding_resets_ranks_of_stocks_that_dropped_out(
    session: Session, mock_adapter: MockAdapter
) -> None:
    build_universe(session, mock_adapter, END_DATE, UniverseSpec())
    build_universe(session, mock_adapter, END_DATE, UniverseSpec(kospi_top=10, kosdaq_top=5))
    session.commit()

    assert len(load_universe(session)) == 15
    assert session.scalar(select(func.count()).select_from(Instrument)) == 150


def test_an_earlier_scan_date_reranks_by_that_dates_market_cap(
    session: Session, mock_adapter: MockAdapter
) -> None:
    from datetime import timedelta

    earlier = END_DATE - timedelta(days=200)

    now = build_universe(session, mock_adapter, END_DATE, UniverseSpec())
    then = build_universe(session, mock_adapter, earlier, UniverseSpec())

    assert len(then) == 120
    assert codes(then, Market.KOSPI) != codes(now, Market.KOSPI)


def test_universe_is_smaller_when_too_few_stocks_qualify(
    session: Session, mock_adapter: MockAdapter, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    members = build_universe(session, mock_adapter, END_DATE, UniverseSpec(kosdaq_top=40))

    assert len(codes(members, Market.KOSDAQ)) == 25  # 30 mock stocks minus 5 excluded
    assert "KOSDAQ universe has only 25 of 40" in caplog.text
