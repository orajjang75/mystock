"""한국투자증권(KIS) Open API adapter. Only a placeholder until step 11."""

from datetime import date

import pandas as pd

from app.adapters.base import Listing, MarketDataAdapter

_ONLY_INTRADAY = "KisAdapter only provides 30-minute bars; use another source for daily data."


class KisAdapter(MarketDataAdapter):
    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> list[Listing]:
        raise NotImplementedError(_ONLY_INTRADAY)

    def fetch_daily_ohlcv(self, code: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError(_ONLY_INTRADAY)

    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError(_ONLY_INTRADAY)

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> pd.DataFrame:
        # TODO(step 11): token refresh, rate limiting, response cache, retries, and a
        # conversion of KIS bar times (bar end) to this interface's bar start times.
        # Keys come from environment variables only.
        raise NotImplementedError("KIS 30-minute bars are implemented in step 11.")

    def fetch_index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError(_ONLY_INTRADAY)
