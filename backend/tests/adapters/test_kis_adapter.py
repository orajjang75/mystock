from datetime import date, datetime
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterUnavailableError, Listing
from app.adapters.factory import get_adapter
from app.adapters.kis_adapter import KisAdapter, aggregate_30m, parse_daily, parse_flow, parse_index
from app.adapters.kis_client import KisClient
from app.core.config import Settings
from app.core.market import KST
from app.db.enums import BarLength, Market
from app.db.models import Instrument, OhlcvIntraday
from app.jobs.ingest import ingest_intraday_30m
from tests.adapters.kis_fake import KEY, SECRET, FakeKis

FRIDAY = date(2026, 10, 16)
AFTER_CLOSE = datetime(2026, 10, 16, 18, 0, tzinfo=KST)


def row(
    hhmm: str, price: int, volume: int = 10, day: str = "20261016", **extra: str
) -> dict[str, str]:
    return {
        "stck_bsop_date": day,
        "stck_cntg_hour": hhmm + "00",
        "stck_prpr": str(price),
        "stck_oprc": str(price - 1),
        "stck_hgpr": str(price + 2),
        "stck_lwpr": str(price - 3),
        "cntg_vol": str(volume),
        **extra,
    }


def adapter(server: FakeKis, now: datetime = AFTER_CLOSE, **kwargs: Any) -> KisAdapter:
    client = KisClient(
        KEY,
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: now,
        sleep=lambda _s: None,
        token_file=None,
    )
    return KisAdapter(client, now=lambda: now, **kwargs)


# --- 1-minute rows -> 30-minute bars ---------------------------------------------------------


def test_minute_rows_become_30_minute_bars_labelled_by_their_start() -> None:
    rows = [
        row("0901", 100, 5),
        row("0915", 110, 7),
        row("0930", 105, 3),
        row("0931", 120, 4),
        row("1000", 130, 6),
    ]

    bars = aggregate_30m(rows, FRIDAY)

    # 09:01 .. 09:30 is the 09:00 bar (the 09:30 row ends at 09:30); 09:31 opens the 09:30 bar
    assert [t.strftime("%H:%M") for t in bars.index] == ["09:00", "09:30"]
    first, second = bars.iloc[0], bars.iloc[1]
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (
        99,
        112,
        97,
        105,
        15,
    )
    assert (second["open"], second["close"], second["volume"]) == (119, 130, 10)
    assert str(pd.DatetimeIndex(bars.index).tz) == "Asia/Seoul"


def test_the_first_and_last_minutes_of_the_session_are_where_they_belong() -> None:
    bars = aggregate_30m([row("0901", 100), row("1530", 200)], FRIDAY)

    assert [t.strftime("%H:%M") for t in bars.index] == [
        "09:00",
        "15:00",
    ]  # 15:30 ends the 15:00 bar


def test_rows_outside_the_session_and_other_days_are_dropped() -> None:
    rows = [row("0900", 90), row("1540", 150), row("1000", 100, day="20261015"), row("0945", 105)]

    bars = aggregate_30m(rows, FRIDAY)

    assert [t.strftime("%H:%M") for t in bars.index] == ["09:30"]  # only the 09:45 row


def test_a_window_with_no_trade_has_no_bar_and_nothing_gives_an_empty_frame() -> None:
    bars = aggregate_30m([row("0901", 100), row("1101", 100)], FRIDAY)

    assert [t.strftime("%H:%M") for t in bars.index] == ["09:00", "11:00"]
    empty = aggregate_30m([], FRIDAY)
    assert empty.empty and list(empty.columns) == ["open", "high", "low", "close", "volume"]


def test_the_same_minute_twice_counts_once() -> None:
    bars = aggregate_30m([row("0901", 100, 5), row("0901", 100, 5)], FRIDAY)

    assert bars["volume"].iloc[0] == 5


# --- paging and caching ----------------------------------------------------------------------


def test_a_whole_session_is_fetched_in_pages_and_adds_up() -> None:
    server = FakeKis()
    kis = adapter(server)

    bars = kis.fetch_intraday_30m("005930", FRIDAY, FRIDAY)

    assert [t.strftime("%H:%M") for t in bars.index] == [
        f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)
    ][:13]
    assert bars["volume"].sum() == 390 * server.minute_volume  # every one of the 390 minutes
    assert len(server.requests) == 4  # 120 + 120 + 120 + 30 rows
    first = server.requests[0].url.params
    assert (
        first["FID_INPUT_HOUR_1"],
        first["FID_INPUT_DATE_1"],
        first["FID_COND_MRKT_DIV_CODE"],
    ) == ("153000", "20261016", "J")
    hours = [r.url.params["FID_INPUT_HOUR_1"] for r in server.requests]
    assert hours == sorted(hours, reverse=True)  # paging backwards through the day


def test_a_finished_day_is_not_fetched_twice() -> None:
    server = FakeKis()
    kis = adapter(server)
    kis.fetch_intraday_30m("005930", FRIDAY, FRIDAY)
    calls = len(server.requests)

    again = kis.fetch_intraday_30m("005930", FRIDAY, FRIDAY)

    assert len(server.requests) == calls
    assert len(again) == 13


def test_today_is_cut_at_the_time_of_the_call_and_not_cached_for_long() -> None:
    server = FakeKis()
    now = datetime(2026, 10, 16, 10, 0, 10, tzinfo=KST)
    kis = adapter(server, now)

    bars = kis.fetch_intraday_30m("005930", FRIDAY, FRIDAY)

    # rows up to 10:00 exist: the 09:00 and 09:30 bars are complete, the 10:00 bar has not started
    assert [t.strftime("%H:%M") for t in bars.index] == ["09:00", "09:30"]
    assert server.requests[0].url.params["FID_INPUT_HOUR_1"] == "100010"


def test_weekends_and_the_hours_before_the_open_cost_no_request() -> None:
    server = FakeKis()
    saturday = datetime(2026, 10, 17, 12, 0, tzinfo=KST)

    adapter(server, saturday).fetch_intraday_30m("005930", date(2026, 10, 17), date(2026, 10, 17))
    adapter(server, datetime(2026, 10, 16, 8, 30, tzinfo=KST)).fetch_intraday_30m(
        "005930", FRIDAY, FRIDAY
    )

    assert server.requests == []


def test_a_range_of_days_is_stitched_in_order() -> None:
    server = FakeKis()
    kis = adapter(server)

    bars = kis.fetch_intraday_30m("005930", date(2026, 10, 14), FRIDAY)

    assert len(bars) == 39
    assert bars.index.is_monotonic_increasing
    assert {t.date() for t in bars.index} == {
        date(2026, 10, 14),
        date(2026, 10, 15),
        date(2026, 10, 16),
    }


def test_the_bars_go_through_the_ingest_job_like_any_other_adapter() -> None:
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import sqlite_engine

    server = FakeKis()
    kis = adapter(server)
    with sessionmaker(bind=sqlite_engine())() as session:
        session.add(Instrument(code="005930", name="삼성전자", market=Market.KOSPI))
        session.flush()

        written = ingest_intraday_30m(
            session, kis, ["005930"], start=FRIDAY, end=FRIDAY, now=AFTER_CLOSE
        )

        assert written == 13
        stored = list(
            session.scalars(
                select(OhlcvIntraday)
                .where(OhlcvIntraday.bar_length == BarLength.M30)
                .order_by(OhlcvIntraday.bar_time)
            )
        )
        assert stored[0].bar_time.hour == 9 and stored[-1].bar_time.hour == 15
        assert session.scalar(select(func.sum(OhlcvIntraday.volume))) == 3900


# --- daily bars, index, flow -----------------------------------------------------------------


def test_daily_bars_are_requested_adjusted_and_paged_over_100_rows() -> None:
    server = FakeKis()
    kis = adapter(server)

    frame = kis.fetch_daily_ohlcv("005930", date(2025, 10, 1), FRIDAY)

    assert len(frame) > 240 and frame.index.is_monotonic_increasing
    assert frame.index.min() == pd.Timestamp("2025-10-01") and frame.index.max() == pd.Timestamp(
        "2026-10-16"
    )
    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    first = server.requests[0].url.params
    assert (first["FID_ORG_ADJ_PRC"], first["FID_PERIOD_DIV_CODE"]) == ("0", "D")  # 수정주가
    assert len(server.requests) >= 3  # 100 rows per call
    assert frame.index.is_unique


def test_daily_parsing_keeps_whole_numbers_and_skips_blank_rows() -> None:
    frame = parse_daily(
        [
            {
                "stck_bsop_date": "20261016",
                "stck_oprc": "100",
                "stck_hgpr": "110",
                "stck_lwpr": "95",
                "stck_clpr": "105",
                "acml_vol": "1,000",
                "acml_tr_pbmn": "105000",
            },
            {
                "stck_bsop_date": "20261015",
                "stck_oprc": "",
                "stck_hgpr": "",
                "stck_lwpr": "",
                "stck_clpr": "",
                "acml_vol": "",
                "acml_tr_pbmn": "",
            },
        ]
    )

    assert list(frame.index) == [pd.Timestamp("2026-10-16")]
    assert frame["volume"].iloc[0] == 1000 and frame["close"].iloc[0] == 105


def test_the_index_is_read_from_its_own_field_names() -> None:
    frame = parse_index(
        [
            {
                "stck_bsop_date": "20261016",
                "bstp_nmix_oprc": "2600.1",
                "bstp_nmix_hgpr": "2620.5",
                "bstp_nmix_lwpr": "2590.0",
                "bstp_nmix_prpr": "2610.2",
            }
        ]
    )

    assert frame.iloc[0].tolist() == [2600.1, 2620.5, 2590.0, 2610.2]


def test_investor_flow_is_converted_from_millions_of_won_and_today_waits_for_the_close() -> None:
    frame = parse_flow(
        [
            {
                "stck_bsop_date": "20261016",
                "frgn_ntby_tr_pbmn": "",
                "orgn_ntby_tr_pbmn": "",
            },  # not final yet
            {
                "stck_bsop_date": "20261015",
                "frgn_ntby_tr_pbmn": "1,250",
                "orgn_ntby_tr_pbmn": "-300",
            },
        ]
    )

    assert list(frame.index) == [pd.Timestamp("2026-10-15")]
    assert frame.iloc[0].tolist() == [1_250_000_000, -300_000_000]


class FakeHistory:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[tuple[date, date]] = []

    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        self.asked.append((start, end))
        if self.fail:
            raise RuntimeError("KRX is down")
        days = pd.bdate_range(start, end, name="trade_date")
        return pd.DataFrame({"foreign_net_buy": 5, "institution_net_buy": 6}, index=days)


def flow_server() -> FakeKis:
    server = FakeKis()
    server.flow_rows = [
        {"stck_bsop_date": "20261016", "frgn_ntby_tr_pbmn": "10", "orgn_ntby_tr_pbmn": "20"},
        {"stck_bsop_date": "20261015", "frgn_ntby_tr_pbmn": "30", "orgn_ntby_tr_pbmn": "40"},
    ]
    return server


def test_investor_flow_older_than_kis_reaches_comes_from_the_history_source() -> None:
    history = FakeHistory()
    kis = adapter(flow_server(), history_source=history)

    frame = kis.fetch_investor_flow("005930", date(2026, 10, 12), FRIDAY)

    assert history.asked == [(date(2026, 10, 12), date(2026, 10, 14))]
    assert list(frame.loc["2026-10-12":"2026-10-14", "foreign_net_buy"]) == [5, 5, 5]
    assert frame.loc[pd.Timestamp("2026-10-16")].to_numpy().tolist() == [
        10_000_000,
        20_000_000,
    ]  # KIS


def test_without_a_history_source_or_when_it_fails_the_older_days_are_simply_missing() -> None:
    server = flow_server()

    plain = adapter(server).fetch_investor_flow("005930", date(2026, 10, 12), FRIDAY)
    broken = adapter(server, history_source=FakeHistory(fail=True)).fetch_investor_flow(
        "005930", date(2026, 10, 12), FRIDAY
    )

    assert (
        list(plain.index)
        == list(broken.index)
        == [pd.Timestamp("2026-10-15"), pd.Timestamp("2026-10-16")]
    )


# --- listings, keys, selection ---------------------------------------------------------------


def test_listings_come_from_the_listings_source() -> None:
    class Source:
        def fetch_listings(
            self, as_of: date, *, limit_per_market: int | None = None
        ) -> list[Listing]:
            return [Listing("005930", "삼성전자", Market.KOSPI, 1_000)]

    kis = adapter(FakeKis(), listings_source=Source())

    assert [item.code for item in kis.fetch_listings(FRIDAY)] == ["005930"]
    with pytest.raises(AdapterUnavailableError, match="listings source"):
        adapter(FakeKis()).fetch_listings(FRIDAY)


def test_selecting_kis_without_keys_fails_at_the_first_request_and_names_the_variables() -> None:
    kis = get_adapter(
        Settings(
            database_url="sqlite://",
            app_username="u",
            app_password="pppp-pppp",
            secret_key="k" * 32,
            adapter="kis",
        )
    )

    with pytest.raises(AdapterUnavailableError, match="KIS_APP_KEY and KIS_APP_SECRET"):
        kis.fetch_daily_ohlcv("005930", FRIDAY, FRIDAY)


def test_the_keys_come_from_the_settings_and_the_server_from_kis_env() -> None:
    settings = Settings(
        database_url="sqlite://", app_username="u", app_password="pppp-pppp", secret_key="k" * 32,
        adapter="kis", kis_app_key=KEY, kis_app_secret=SECRET, kis_env="paper", kis_token_file="",
    )  # fmt: skip

    built = get_adapter(settings)
    assert isinstance(built, KisAdapter)
    client = built.client

    assert isinstance(client, KisClient)
    assert client._base == "https://openapivts.koreainvestment.com:29443"
    assert client._limiter._interval == 0.5  # 2 requests a second on the paper server
