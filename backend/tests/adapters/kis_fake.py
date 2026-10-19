"""A fake KIS server for the tests: answers the way KIS's documentation says it does."""

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import httpx

from app.core.market import is_trading_day

KEY, SECRET = "PSkey-0123456789", "secret-abcdefghij-0123456789"


class FakeKis:
    """``handler`` is an httpx MockTransport handler. Failures are queued in ``failures``: each
    entry is a callable returning the response for the next *data* request."""

    def __init__(self) -> None:
        self.token_value = "tok-abcdef-0001"
        self.token_issues = 0
        self.token_requests: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.failures: list[Callable[[], httpx.Response]] = []
        self.token_error: httpx.Response | None = None
        self.minute_volume = 10
        self.flow_rows: list[dict[str, str]] = []
        self.index_rows: list[dict[str, str]] = []

    # -- plumbing --------------------------------------------------------------------------------

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler), base_url="https://kis.test"
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth2/tokenP":
            body = json.loads(request.content)
            self.token_requests.append(body)
            if self.token_error is not None:
                return self.token_error
            self.token_issues += 1
            self.token_value = f"tok-abcdef-{self.token_issues:04d}"
            return httpx.Response(
                200,
                json={
                    "access_token": self.token_value,
                    "token_type": "Bearer",
                    "expires_in": 86400,
                    "access_token_token_expired": "2099-01-01 00:00:00",
                },
            )
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.token_value}":
            return httpx.Response(
                200,
                json={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."},
            )
        if self.failures:
            return self.failures.pop(0)()
        params = dict(request.url.params)
        if path.endswith("inquire-time-dailychartprice"):
            return httpx.Response(200, json=self._minutes(params))
        if path.endswith("inquire-daily-itemchartprice"):
            return httpx.Response(200, json=self._daily(params))
        if path.endswith("inquire-investor"):
            return httpx.Response(
                200, json={"rt_cd": "0", "msg_cd": "MCA00000", "output": self.flow_rows}
            )
        if path.endswith("inquire-daily-indexchartprice"):
            return httpx.Response(200, json={"rt_cd": "0", "output2": self.index_rows})
        return httpx.Response(404, json={"rt_cd": "1", "msg_cd": "NOPE", "msg1": path})

    # -- data ------------------------------------------------------------------------------------

    @staticmethod
    def ok(output2: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": output2,
        }

    def _minutes(self, params: dict[str, str]) -> dict[str, Any]:
        day = datetime.strptime(params["FID_INPUT_DATE_1"], "%Y%m%d").date()
        limit = params["FID_INPUT_HOUR_1"]
        rows = []
        stamp = datetime.combine(day, time(9, 1))
        while stamp.time() <= time(15, 30):
            label = stamp.strftime("%H%M%S")
            if label <= limit:
                price = 10_000 + stamp.hour * 60 + stamp.minute  # a price that tells the minute
                rows.append(
                    {
                        "stck_bsop_date": day.strftime("%Y%m%d"),
                        "stck_cntg_hour": label,
                        "stck_prpr": str(price),
                        "stck_oprc": str(price - 1),
                        "stck_hgpr": str(price + 2),
                        "stck_lwpr": str(price - 3),
                        "cntg_vol": str(self.minute_volume),
                        "acml_tr_pbmn": "0",
                    }
                )
            stamp += timedelta(minutes=1)
        if day == date(2026, 10, 16) and limit >= "154000":
            rows.append({**rows[-1], "stck_cntg_hour": "154000"})  # the closing-price print
        return self.ok(list(reversed(rows))[:120])  # newest first, at most 120

    def _daily(self, params: dict[str, str]) -> dict[str, Any]:
        first = datetime.strptime(params.get("FID_INPUT_DATE_1", "20260105"), "%Y%m%d").date()
        last = datetime.strptime(params.get("FID_INPUT_DATE_2", "20260109"), "%Y%m%d").date()
        days = []
        day = last
        while day >= first:
            if is_trading_day(day):
                days.append(day)
            day -= timedelta(days=1)
        rows = [
            {
                "stck_bsop_date": d.strftime("%Y%m%d"),
                "stck_clpr": str(1000 + d.toordinal() % 50),
                "stck_oprc": str(1000 + d.toordinal() % 50 - 1),
                "stck_hgpr": str(1000 + d.toordinal() % 50 + 3),
                "stck_lwpr": str(1000 + d.toordinal() % 50 - 4),
                "acml_vol": "12345",
                "acml_tr_pbmn": "12345678",
            }
            for d in days[:100]
        ]
        return self.ok(rows)
