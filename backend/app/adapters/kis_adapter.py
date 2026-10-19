"""한국투자증권(KIS) Open API adapter: 30-minute bars, daily bars, investor flow, KOSPI index.

Which call serves what (paths and field names from KIS's sample code, github.com/koreainvestment/
open-trading-api; see docs/real-data.md for the limits that matter):

- 30-minute bars: KIS only has 1-minute bars (``inquire-time-dailychartprice``, FHKST03010230,
  up to 120 rows per call, about one year kept). They are fetched a day at a time, paging
  backwards from the close, and aggregated here. A 1-minute bar is labelled with its *end*
  (09:01 covers 09:00-09:01), the interface wants the 30-minute bar's *start* time.
- Daily bars: ``inquire-daily-itemchartprice`` (FHKST03010100), 100 rows per call, adjusted
  prices (``FID_ORG_ADJ_PRC=0``).
- Investor flow: ``inquire-investor`` (FHKST01010900), roughly the last 30 sessions, today's row
  only after the close. Older days come from ``history_source`` (pykrx) when there is one.
- KOSPI index: ``inquire-daily-indexchartprice`` (FHKUP03500100).
- Listings with market caps: KIS has no "who was big on this date" call; they come from
  ``listings_source`` (pykrx), as of any past date.

Keys come from the environment only (``KIS_APP_KEY``, ``KIS_APP_SECRET``).

Not yet run against the live service (no keys were available while writing this): field names
follow KIS's sample code, the paging and unit assumptions are listed in docs/real-data.md and the
whole thing is covered by tests against a fake server. ``investor flow`` values are taken to be in
millions of won, as KIS documents the ``*_tr_pbmn`` fields; check one day against HTS before
trusting the 수급 signals.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.adapters.base import (
    DAILY_COLUMNS,
    FLOW_COLUMNS,
    INDEX_COLUMNS,
    INTRADAY_COLUMNS,
    AdapterUnavailableError,
    Listing,
    MarketDataAdapter,
)
from app.adapters.kis_client import KisClient
from app.core.market import KST, MARKET_CLOSE, MARKET_OPEN, is_trading_day

logger = logging.getLogger(__name__)

PATH_MINUTE = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
PATH_DAILY = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
PATH_INVESTOR = "/uapi/domestic-stock/v1/quotations/inquire-investor"
PATH_INDEX = "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"

MINUTE_ROWS = 120  # per call, real account
DAILY_ROWS = 100
MAX_PAGES = 8  # a session has 390 minutes: four pages, with room to spare
WON_PER_MILLION = 1_000_000
INDEX_CODES = {"KOSPI": "0001"}

PAST_TTL = 24 * 3600.0  # a finished day's minute bars cannot change
TODAY_TTL = 15.0  # but twice within one tick should cost one request
DAILY_TTL = 6 * 3600.0  # adjusted prices may be restated overnight, so not forever

_ONE_MINUTE = pd.Timedelta(minutes=1)


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _number(value: Any) -> float:
    """KIS sends every number as text; an empty string means "no value"."""
    try:
        return float(str(value).replace(",", "")) if str(value).strip() != "" else float("nan")
    except ValueError:
        return float("nan")


# --- pure conversions (tested without any network) -----------------------------------------------


def aggregate_30m(rows: list[dict[str, Any]], day: date) -> pd.DataFrame:
    """1-minute rows of one session as 30-minute bars labelled by their start time (KST).

    A bar opens with the first trade, closes with the last and adds up the volume. A 30-minute
    window without a single trade has no bar. Rows outside the regular session (the 15:40
    closing price, the 09:00 pre-open) are dropped.
    """
    records = []
    for row in rows:
        label = str(row.get("stck_cntg_hour", ""))
        if len(label) != 6 or row.get("stck_bsop_date") != _ymd(day):
            continue
        end = pd.Timestamp(datetime.combine(day, time(int(label[:2]), int(label[2:4]), 0)), tz=KST)
        start = end - _ONE_MINUTE
        if not (
            pd.Timestamp(datetime.combine(day, MARKET_OPEN), tz=KST)
            <= start
            < pd.Timestamp(datetime.combine(day, MARKET_CLOSE), tz=KST)
        ):
            continue
        records.append(
            {
                "minute": start,
                "open": _number(row.get("stck_oprc")),
                "high": _number(row.get("stck_hgpr")),
                "low": _number(row.get("stck_lwpr")),
                "close": _number(row.get("stck_prpr")),
                "volume": _number(row.get("cntg_vol")),
            }
        )
    if not records:
        return pd.DataFrame(
            columns=INTRADAY_COLUMNS, index=pd.DatetimeIndex([], tz=KST, name="bar_time")
        )
    minutes = pd.DataFrame(records).drop_duplicates("minute").sort_values("minute")
    minutes["bar_time"] = minutes["minute"].dt.floor("30min")
    grouped = minutes.groupby("bar_time")
    bars = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum().fillna(0).astype("int64"),
        }
    )
    bars.index = pd.DatetimeIndex(bars.index, name="bar_time")
    return bars[INTRADAY_COLUMNS]


def parse_daily(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trade_date": [r.get("stck_bsop_date") for r in rows],
            "open": [_number(r.get("stck_oprc")) for r in rows],
            "high": [_number(r.get("stck_hgpr")) for r in rows],
            "low": [_number(r.get("stck_lwpr")) for r in rows],
            "close": [_number(r.get("stck_clpr")) for r in rows],
            "volume": [_number(r.get("acml_vol")) for r in rows],
            "trading_value": [_number(r.get("acml_tr_pbmn")) for r in rows],
        }
    )
    frame = frame[frame["trade_date"].astype(bool)].dropna(subset=["close"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    frame = frame.drop_duplicates("trade_date").set_index("trade_date").sort_index()
    frame[["volume", "trading_value"]] = (
        frame[["volume", "trading_value"]].fillna(0).astype("int64")
    )
    return frame[DAILY_COLUMNS]


def parse_flow(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Net buying in won. KIS gives ``*_tr_pbmn`` in millions of won; a day whose value is still
    blank (today, before the close) is left out rather than stored as 0."""
    out = []
    for r in rows:
        foreign, institution = (
            _number(r.get("frgn_ntby_tr_pbmn")),
            _number(r.get("orgn_ntby_tr_pbmn")),
        )
        if not r.get("stck_bsop_date") or np.isnan(foreign) or np.isnan(institution):
            continue
        out.append(
            (
                pd.Timestamp(r["stck_bsop_date"]),
                round(foreign * WON_PER_MILLION),
                round(institution * WON_PER_MILLION),
            )
        )
    frame = pd.DataFrame(out, columns=["trade_date", *FLOW_COLUMNS]).drop_duplicates("trade_date")
    frame = frame.set_index("trade_date").sort_index()
    frame.index = pd.DatetimeIndex(frame.index, name="trade_date")
    return frame.astype("int64")


def parse_index(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trade_date": [r.get("stck_bsop_date") for r in rows],
            "open": [_number(r.get("bstp_nmix_oprc")) for r in rows],
            "high": [_number(r.get("bstp_nmix_hgpr")) for r in rows],
            "low": [_number(r.get("bstp_nmix_lwpr")) for r in rows],
            "close": [_number(r.get("bstp_nmix_prpr")) for r in rows],
        }
    )
    frame = frame[frame["trade_date"].astype(bool)].dropna(subset=["close"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    return frame.drop_duplicates("trade_date").set_index("trade_date").sort_index()[INDEX_COLUMNS]


# --- the adapter ---------------------------------------------------------------------------------


class KisAdapter(MarketDataAdapter):
    def __init__(
        self,
        client: KisClient | Callable[[], KisClient] | None = None,
        *,
        listings_source: MarketDataAdapter | None = None,
        history_source: MarketDataAdapter | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(KST),
    ) -> None:
        self._client_or_factory = client
        self._client: KisClient | None = client if isinstance(client, KisClient) else None
        self._listings = listings_source
        self._history = history_source
        self._now = now

    @property
    def client(self) -> KisClient:
        """Built on first use, so that selecting ``ADAPTER=kis`` without keys fails at the first
        request (with a message naming the variables) and not while the app starts."""
        if self._client is None:
            if callable(self._client_or_factory):
                self._client = self._client_or_factory()
            else:
                raise AdapterUnavailableError(
                    "KIS_APP_KEY and KIS_APP_SECRET are not set; the KIS adapter needs both."
                )
        return self._client

    # --- 30-minute bars ------------------------------------------------------------------------

    def _minute_rows(self, code: str, day: date, until: time) -> list[dict[str, Any]]:
        """Every 1-minute row of ``day`` up to ``until``, paging backwards from there."""
        past = day < self._now().date()
        rows: list[dict[str, Any]] = []
        cursor = until
        for _ in range(MAX_PAGES):
            body = self.client.get(
                PATH_MINUTE,
                "FHKST03010230",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_HOUR_1": cursor.strftime("%H%M%S"),
                    "FID_INPUT_DATE_1": _ymd(day),
                    "FID_PW_DATA_INCU_YN": "N",
                },
                ttl=PAST_TTL if past else TODAY_TTL,
            )
            page = [r for r in body.get("output2") or [] if r.get("stck_bsop_date") == _ymd(day)]
            if not page:
                break
            rows += page
            earliest = min(str(r["stck_cntg_hour"]) for r in page)
            earliest_time = time(int(earliest[:2]), int(earliest[2:4]), int(earliest[4:]))
            if earliest_time <= time(9, 1) or earliest_time >= cursor:
                break
            cursor = (datetime.combine(day, earliest_time) - timedelta(minutes=1)).time()
        return rows

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> pd.DataFrame:
        now = self._now()
        frames = []
        day = start
        while day <= min(end, now.date()):
            if is_trading_day(day) and not (day == now.date() and now.time() < time(9, 1)):
                until = (
                    MARKET_CLOSE
                    if day < now.date()
                    else min(now.time().replace(microsecond=0), MARKET_CLOSE)
                )
                frame = aggregate_30m(self._minute_rows(code, day, until), day)
                if not frame.empty:
                    frames.append(frame)
            day += timedelta(days=1)
        if not frames:
            return pd.DataFrame(
                columns=INTRADAY_COLUMNS, index=pd.DatetimeIndex([], tz=KST, name="bar_time")
            )
        return pd.concat(frames)[INTRADAY_COLUMNS]

    # --- daily bars, index, flow ---------------------------------------------------------------

    def _paged(
        self, path: str, tr_id: str, base: dict[str, str], start: date, end: date, per_page: int
    ) -> list[dict[str, Any]]:
        """Rows of a date-ranged call that returns the newest ``per_page`` rows first."""
        rows: list[dict[str, Any]] = []
        upper = end
        past = end < self._now().date()
        for _ in range(60):
            body = self.client.get(
                path,
                tr_id,
                {**base, "FID_INPUT_DATE_1": _ymd(start), "FID_INPUT_DATE_2": _ymd(upper)},
                ttl=DAILY_TTL if past else 60.0,
            )
            page = body.get("output2") or []
            dates = [str(r["stck_bsop_date"]) for r in page if r.get("stck_bsop_date")]
            if not dates:
                break
            rows += page
            earliest = datetime.strptime(min(dates), "%Y%m%d").date()
            if earliest <= start or len(page) < per_page:
                break
            upper = earliest - timedelta(days=1)
        return rows

    def fetch_daily_ohlcv(self, code: str, start: date, end: date) -> pd.DataFrame:
        rows = self._paged(
            PATH_DAILY,
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",  # 0 = 수정주가
            },
            start,
            end,
            DAILY_ROWS,
        )
        frame = parse_daily(rows)
        return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)]

    def fetch_index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        rows = self._paged(
            PATH_INDEX,
            "FHKUP03500100",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": INDEX_CODES[index_code],
                "FID_PERIOD_DIV_CODE": "D",
            },
            start,
            end,
            50,
        )
        return parse_index(rows).loc[pd.Timestamp(start) : pd.Timestamp(end)]

    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        body = self.client.get(
            PATH_INVESTOR,
            "FHKST01010900",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            ttl=60.0 if end >= self._now().date() else DAILY_TTL,
        )
        recent = parse_flow(body.get("output") or [])
        frame = recent.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        covered_from = recent.index.min().date() if len(recent) else end + timedelta(days=1)
        if start < covered_from and self._history is not None:
            # KIS only reaches back about 30 sessions; the rest from the historical source
            try:
                older = self._history.fetch_investor_flow(
                    code, start, covered_from - timedelta(days=1)
                )
                frame = pd.concat([older, frame]).sort_index()
                frame = frame[~frame.index.duplicated(keep="last")]
            except Exception as error:  # the older days are then simply "수급 미반영"
                logger.warning("no older investor flow for %s: %s", code, type(error).__name__)
        return frame[FLOW_COLUMNS]

    # --- listings ------------------------------------------------------------------------------

    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> list[Listing]:
        if self._listings is None:
            raise AdapterUnavailableError(
                "KIS has no ranking by market cap as of a date; give the adapter a listings source."
            )
        return self._listings.fetch_listings(as_of, limit_per_market=limit_per_market)
