"""PykrxAdapter against a fake pykrx module (no network, no KRX account needed)."""

import contextlib
from datetime import date
from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from app.adapters.pykrx_adapter import PykrxAdapter
from app.db.enums import Market

DAY = date(2026, 10, 16)
DATES = pd.DatetimeIndex(["2026-10-15", "2026-10-16"], name="날짜")


def fake_stock(*, ohlcv_has_value: bool = True) -> SimpleNamespace:
    caps = {
        "KOSPI": pd.DataFrame(
            {"시가총액": [900, 500, 100], "거래량": [10, 20, 0]},
            index=pd.Index(["005930", "005935", "000660"], name="티커"),
        ),
        "KOSDAQ": pd.DataFrame(
            {"시가총액": [50, 40], "거래량": [5, 6]},
            index=pd.Index(["247540", "086520"], name="티커"),
        ),
    }
    names = {"005930": "삼성전자", "005935": "삼성전자우", "000660": "SK하이닉스"}

    def get_market_cap(*args: Any, **kwargs: Any) -> pd.DataFrame:
        if len(args) == 3:  # per ticker over a period
            return pd.DataFrame({"거래대금": [111, 222]}, index=DATES)
        return caps[kwargs["market"]]

    def get_market_ohlcv(*args: Any, **kwargs: Any) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "시가": [1, 2],
                "고가": [3, 4],
                "저가": [1, 2],
                "종가": [2, 3],
                "거래량": [10, 20],
                "등락률": [0.1, 0.2],
            },
            index=DATES,
        )
        if ohlcv_has_value:
            frame["거래대금"] = [20, 60]
        assert kwargs.get("adjusted") is True  # 수정주가
        return frame

    return SimpleNamespace(
        get_market_cap=get_market_cap,
        get_market_ohlcv=get_market_ohlcv,
        get_market_ticker_name=lambda code: names.get(code, f"종목{code}"),
        get_market_trading_value_by_date=lambda *a, **k: pd.DataFrame(
            {"기관합계": [-5, 7], "기타법인": [0, 0], "개인": [1, 1], "외국인합계": [9, -3]},
            index=DATES,
        ),
        get_index_ohlcv=lambda *a, **k: pd.DataFrame(
            {"시가": [10.0, 11.0], "고가": [12.0, 13.0], "저가": [9.0, 10.0], "종가": [11.0, 12.0]},
            index=DATES,
        ),
    )


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> PykrxAdapter:
    instance = PykrxAdapter()
    monkeypatch.setattr(PykrxAdapter, "_stock", lambda self: fake_stock())
    return instance


def test_listings_flag_preferred_shares_and_halted_stocks(adapter: PykrxAdapter) -> None:
    listings = {item.code: item for item in adapter.fetch_listings(DAY)}

    assert listings["005930"].market is Market.KOSPI
    assert listings["005930"].market_cap == 900
    assert listings["005930"].name == "삼성전자"
    assert listings["005935"].is_preferred  # code does not end in 0
    assert not listings["005930"].is_preferred
    assert listings["000660"].is_halted  # no volume on the as-of date
    assert not listings["005930"].is_halted
    assert listings["247540"].market is Market.KOSDAQ


def test_listings_limit_keeps_the_largest_per_market(adapter: PykrxAdapter) -> None:
    listings = adapter.fetch_listings(DAY, limit_per_market=1)

    assert [item.code for item in listings] == ["005930", "247540"]


def test_daily_bars_use_english_columns_and_a_trade_date_index(adapter: PykrxAdapter) -> None:
    frame = adapter.fetch_daily_ohlcv("005930", DAY, DAY)

    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    assert frame.index.name == "trade_date"
    assert list(frame["trading_value"]) == [20, 60]


def test_trading_value_falls_back_to_the_market_cap_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PykrxAdapter, "_stock", lambda self: fake_stock(ohlcv_has_value=False))

    frame = PykrxAdapter().fetch_daily_ohlcv("005930", DAY, DAY)

    assert list(frame["trading_value"]) == [111, 222]


def test_investor_flow_maps_foreign_and_institution(adapter: PykrxAdapter) -> None:
    flow = adapter.fetch_investor_flow("005930", DAY, DAY)

    assert list(flow.columns) == ["foreign_net_buy", "institution_net_buy"]
    assert list(flow["foreign_net_buy"]) == [9, -3]
    assert list(flow["institution_net_buy"]) == [-5, 7]


def test_kospi_index_uses_ticker_1001(adapter: PykrxAdapter) -> None:
    frame = adapter.fetch_index_daily("KOSPI", DAY, DAY)

    assert list(frame.columns) == ["open", "high", "low", "close"]
    assert list(frame["close"]) == [11.0, 12.0]


@pytest.mark.skipif(find_spec("pykrx") is not None, reason="would really log in to KRX")
def test_krx_credentials_are_exported_before_pykrx_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from app.adapters.base import AdapterUnavailableError

    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)

    with contextlib.suppress(AdapterUnavailableError):  # pykrx itself is not installed here
        PykrxAdapter(krx_id="me", krx_pw="pw")._stock()

    assert os.environ["KRX_ID"] == "me"
    assert os.environ["KRX_PW"] == "pw"
    monkeypatch.delenv("KRX_ID")
    monkeypatch.delenv("KRX_PW")
