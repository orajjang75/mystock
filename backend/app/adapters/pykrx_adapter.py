"""pykrx adapter: daily bars, market caps and investor net buying from KRX.

pykrx is an optional dependency (``uv sync --extra pykrx``) and is imported lazily so that this
module imports cleanly without it or without network access.

pykrx >= 1.2 logs in to the KRX data portal when it is imported, so ``KRX_ID`` and ``KRX_PW`` must
be set (environment variables or .env); the adapter exports them before importing.

Not yet verified against the live KRX service (no account was available while writing this):
the column mapping follows pykrx's documented output and is covered by tests with a fake module.

Known gaps, which must be filled from another source before real-data operation:
- pykrx has no administrative-issue or investment-warning flags, so those are always False.
  Halted stocks are inferred from zero volume on the as-of date.
- pykrx has no intraday bars; use the KIS adapter (step 11).
- Preferred shares are detected by the Korean ticker convention: common stock codes end in "0".
"""

import importlib
import os
from datetime import date
from types import ModuleType

import pandas as pd

from app.adapters.base import (
    DAILY_COLUMNS,
    FLOW_COLUMNS,
    INDEX_COLUMNS,
    AdapterUnavailableError,
    Listing,
    MarketDataAdapter,
)
from app.db.enums import Market

_INDEX_TICKERS = {"KOSPI": "1001"}


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _tidy(frame: pd.DataFrame, rename: dict[str, str], columns: list[str]) -> pd.DataFrame:
    frame = frame.rename(columns=rename)[columns]
    frame.index = pd.DatetimeIndex(frame.index, name="trade_date").normalize()
    return frame.sort_index()


class PykrxAdapter(MarketDataAdapter):
    def __init__(self, krx_id: str | None = None, krx_pw: str | None = None) -> None:
        self._krx_id = krx_id
        self._krx_pw = krx_pw

    def _stock(self) -> ModuleType:
        if self._krx_id and self._krx_pw:
            os.environ.setdefault("KRX_ID", self._krx_id)
            os.environ.setdefault("KRX_PW", self._krx_pw)
        try:
            return importlib.import_module("pykrx.stock")
        except ImportError as exc:
            raise AdapterUnavailableError(
                "pykrx is not installed; run `uv sync --extra pykrx`."
            ) from exc

    def fetch_listings(self, as_of: date, *, limit_per_market: int | None = None) -> list[Listing]:
        stock = self._stock()
        listings: list[Listing] = []
        for market in (Market.KOSPI, Market.KOSDAQ):
            caps = stock.get_market_cap(_ymd(as_of), market=market.value)
            caps = caps.sort_values("시가총액", ascending=False)
            if limit_per_market:
                caps = caps.head(limit_per_market)
            for ticker, row in caps.iterrows():
                code = str(ticker)
                listings.append(
                    Listing(
                        code=code,
                        name=str(stock.get_market_ticker_name(code)),
                        market=market,
                        market_cap=int(row["시가총액"]),
                        is_preferred=not code.endswith("0"),
                        is_halted=int(row["거래량"]) == 0,
                    )
                )
        return listings

    def fetch_daily_ohlcv(self, code: str, start: date, end: date) -> pd.DataFrame:
        stock = self._stock()
        frame = stock.get_market_ohlcv(_ymd(start), _ymd(end), code, adjusted=True)
        if "거래대금" not in frame.columns:
            # Older pykrx releases return OHLCV only; the market-cap table carries 거래대금.
            caps = stock.get_market_cap(_ymd(start), _ymd(end), code)
            frame = frame.join(caps["거래대금"], how="left")
        rename = {
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "거래대금": "trading_value",
        }
        return _tidy(frame, rename, DAILY_COLUMNS)

    def fetch_investor_flow(self, code: str, start: date, end: date) -> pd.DataFrame:
        frame = self._stock().get_market_trading_value_by_date(_ymd(start), _ymd(end), code)
        return _tidy(
            frame,
            {"외국인합계": "foreign_net_buy", "기관합계": "institution_net_buy"},
            FLOW_COLUMNS,
        )

    def fetch_intraday_30m(self, code: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError("pykrx has no intraday bars; use the KIS adapter.")

    def fetch_index_daily(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        frame = self._stock().get_index_ohlcv(_ymd(start), _ymd(end), _INDEX_TICKERS[index_code])
        rename = {"시가": "open", "고가": "high", "저가": "low", "종가": "close"}
        return _tidy(frame, rename, INDEX_COLUMNS)
