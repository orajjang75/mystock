"""Market-data source interface (PRD 8장 "시세 소스").

Every real or fake source implements this one interface, so switching sources never touches the
engine, services or jobs. Frames are pandas DataFrames with the layouts below; adapters must
hand back **confirmed** data only (CLAUDE.md 규칙 4) and prices adjusted for splits and dividends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.db.enums import Market

DAILY_COLUMNS = ["open", "high", "low", "close", "volume", "trading_value"]
FLOW_COLUMNS = ["foreign_net_buy", "institution_net_buy"]
INTRADAY_COLUMNS = ["open", "high", "low", "close", "volume"]
INDEX_COLUMNS = ["open", "high", "low", "close"]


class AdapterUnavailableError(RuntimeError):
    """The adapter's backing library or credentials are not available."""


@dataclass(frozen=True, slots=True)
class Listing:
    """One listed stock as of a date (종목 마스터 + 시가총액)."""

    code: str
    name: str
    market: Market
    market_cap: int  # 원
    is_preferred: bool = False  # 우선주
    is_admin_issue: bool = False  # 관리종목
    is_halted: bool = False  # 거래정지
    is_warning: bool = False  # 투자경고·위험


class MarketDataAdapter(ABC):
    @abstractmethod
    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> list[Listing]:
        """KOSPI and KOSDAQ stocks with market caps as of ``as_of``.

        With ``limit_per_market`` only the largest N stocks of each market are returned, which
        lets a real source avoid looking up thousands of names.
        """

    @abstractmethod
    def fetch_daily_ohlcv(self, code: str, start: date, end: date) -> pd.DataFrame:
        """Daily bars for ``start..end`` inclusive.

        Index: ``trade_date`` (tz-naive DatetimeIndex, ascending). Columns: ``DAILY_COLUMNS``;
        ``trading_value`` is in 원.
        """

    @abstractmethod
    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        """Daily net-buy amounts in 원. Same index as daily bars; columns: ``FLOW_COLUMNS``."""

    @abstractmethod
    def fetch_intraday_30m(self, code: str, start: date, end: date) -> pd.DataFrame:
        """Closed 30-minute regular-session bars for ``start..end`` inclusive.

        Index: ``bar_time`` = the bar's **start** time (09:00, 09:30, ..., 15:00), tz-aware
        Asia/Seoul. Columns: ``INTRADAY_COLUMNS``.
        """

    @abstractmethod
    def fetch_index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        """Daily index bars (``index_code`` is "KOSPI"), laid out like ``fetch_daily_ohlcv``."""
