import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.adapters.kis_client import (
    KisApiError,
    KisAuthError,
    KisClient,
    KisUnavailableError,
    RateLimiter,
)
from app.core.market import KST
from app.core.secrets import forget_runtime_secrets, redact, secret_values
from tests.adapters.kis_fake import KEY, SECRET, FakeKis

PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
PARAMS = {"FID_INPUT_ISCD": "005930"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 16, 9, 0, tzinfo=KST)
        self.monotonic = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.monotonic += seconds
        self.now += timedelta(seconds=seconds)


def make(server: FakeKis, clock: Clock, **options: object) -> KisClient:
    return KisClient(
        KEY,
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        sleep=clock.sleep,
        clock=lambda: clock.monotonic,
        token_file=None,
        **options,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _clean_runtime_secrets() -> None:
    forget_runtime_secrets()


def test_a_request_carries_the_documented_headers_and_gets_a_token_first() -> None:
    server, clock = FakeKis(), Clock()

    make(server, clock).get(PATH, "FHKST03010100", PARAMS)

    assert server.token_requests == [
        {"grant_type": "client_credentials", "appkey": KEY, "appsecret": SECRET}
    ]
    sent = server.requests[0].headers
    assert sent["authorization"] == "Bearer tok-abcdef-0001"
    assert (sent["appkey"], sent["appsecret"], sent["tr_id"], sent["custtype"]) == (
        KEY,
        SECRET,
        "FHKST03010100",
        "P",
    )
    assert server.requests[0].url.params["FID_INPUT_ISCD"] == "005930"


def test_the_token_is_reused_until_shortly_before_it_runs_out() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock)

    client.get(PATH, "X", PARAMS)
    clock.now += timedelta(hours=23)
    client.get(PATH, "X", PARAMS)
    assert server.token_issues == 1

    clock.now += timedelta(hours=1)  # inside the ten-minute margin of the 24 hours
    client.get(PATH, "X", PARAMS)

    assert server.token_issues == 2


def test_the_token_is_masked_everywhere_once_it_exists() -> None:
    server, clock = FakeKis(), Clock()

    make(server, clock).get(PATH, "X", PARAMS)

    assert "tok-abcdef-0001" in secret_values(
        __import__("app.core.config", fromlist=["x"]).Settings(
            database_url="sqlite://",
            app_username="u",
            app_password="pppp-pppp",
            secret_key="k" * 32,
        )
    )
    assert redact("Bearer tok-abcdef-0001 failed") == "Bearer *** failed"


def test_the_token_file_keeps_it_across_restarts_and_is_private(tmp_path: Path) -> None:
    server, clock = FakeKis(), Clock()
    path = tmp_path / "kis" / "token.json"
    KisClient(
        KEY,
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        token_file=str(path),
    ).get(PATH, "X", PARAMS)

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = KisClient(
        KEY,
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        token_file=str(path),
    )
    again.get(PATH, "X", PARAMS)

    assert server.token_issues == 1  # the second client read the file
    assert "appsecret" not in path.read_text()


def test_a_token_of_another_key_or_server_is_not_reused(tmp_path: Path) -> None:
    server, clock = FakeKis(), Clock()
    path = str(tmp_path / "token.json")
    KisClient(
        KEY,
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        token_file=path,
    ).get(PATH, "X", PARAMS)

    other_key = KisClient(
        "another-key-9999",
        SECRET,
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        token_file=path,
    )
    other_key.get(PATH, "X", PARAMS)
    paper = KisClient(
        KEY,
        SECRET,
        env="paper",
        http=server.client(),
        base_url="https://kis.test",
        now=lambda: clock.now,
        token_file=path,
    )
    paper.get(PATH, "X", PARAMS)

    assert server.token_issues == 3


def test_a_refused_token_request_says_why_without_the_keys() -> None:
    server, clock = FakeKis(), Clock()
    server.token_error = httpx.Response(
        403, json={"error_description": f"invalid appkey {KEY}", "error_code": "EGW00103"}
    )

    with pytest.raises(KisAuthError) as error:
        make(server, clock).get(PATH, "X", PARAMS)

    assert "EGW00103" in str(error.value)
    assert KEY not in str(error.value) and SECRET not in str(error.value)


def test_a_second_token_within_a_minute_is_not_even_asked_for() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock)
    client.get(PATH, "X", PARAMS)
    server.token_value = "something-else"  # the server no longer accepts ours: "expired"
    server.failures.clear()

    with pytest.raises(KisAuthError, match="once a minute"):
        client.get(PATH, "X", PARAMS)

    assert server.token_issues == 1  # no request was wasted on a refusal that was certain


def test_an_expired_token_answer_gets_a_fresh_token_once() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock)
    client.get(PATH, "X", PARAMS)
    clock.now += timedelta(minutes=2)
    server.token_value = "tok-rotated-by-kis"  # KIS invalidated ours early

    # the client still holds the old token: the first reply is EGW00123, then it re-issues
    body = client.get(PATH, "X", {"FID_INPUT_DATE_1": "20260105", "FID_INPUT_DATE_2": "20260109"})

    assert body["rt_cd"] == "0"
    assert server.token_issues == 2


def test_the_rate_limit_is_kept_by_waiting_not_by_failing() -> None:
    clock = Clock()
    limiter = RateLimiter(2.0, clock=lambda: clock.monotonic, sleep=clock.sleep)

    for _ in range(5):
        limiter.acquire()

    assert sum(clock.slept) == pytest.approx(
        2.0
    )  # 5 requests at 2 per second start 2 s apart overall


def test_requests_through_the_client_are_spaced_by_the_limit() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock, max_rps=4.0)

    for _ in range(9):
        client.get(PATH, "X", {"FID_INPUT_ISCD": str(_)})

    assert sum(clock.slept) == pytest.approx(2.0)  # 9 requests at 4 per second


def test_an_exceeded_rate_limit_is_waited_out_and_retried() -> None:
    server, clock = FakeKis(), Clock()
    server.failures = [
        lambda: httpx.Response(
            200,
            json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."},
        )
    ] * 2
    client = make(server, clock)

    body = client.get(PATH, "X", PARAMS)

    assert body["rt_cd"] == "0"
    assert client.calls == 3
    assert clock.slept[-2:] == [1.0, 1.0]  # at least a second per rate-limit answer


def test_server_trouble_is_retried_with_growing_pauses_then_reported() -> None:
    server, clock = FakeKis(), Clock()
    server.failures = [lambda: httpx.Response(503, text="busy")] * 4
    client = make(server, clock, retries=3)

    with pytest.raises(KisUnavailableError, match="after 4 tries"):
        client.get(PATH, "X", PARAMS)

    assert [round(s, 2) for s in clock.slept if s >= 0.5] == [0.5, 1.0, 2.0, 4.0]


def test_a_network_error_is_retried_too() -> None:
    server, clock = FakeKis(), Clock()
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/oauth2/tokenP":
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("boom", request=request)
        return server.handler(request)

    client = KisClient(
        KEY,
        SECRET,
        http=httpx.Client(transport=httpx.MockTransport(flaky)),
        base_url="https://kis.test",
        now=lambda: clock.now,
        sleep=clock.sleep,
        clock=lambda: clock.monotonic,
    )

    assert client.get(PATH, "X", PARAMS)["rt_cd"] == "0"


def test_an_error_answer_is_not_retried_and_keeps_the_codes() -> None:
    server, clock = FakeKis(), Clock()
    server.failures = [
        lambda: httpx.Response(
            200, json={"rt_cd": "1", "msg_cd": "OPSQ2000", "msg1": "없는 종목입니다"}
        )
    ]
    client = make(server, clock)

    with pytest.raises(KisApiError) as error:
        client.get(PATH, "X", PARAMS)

    assert error.value.msg_cd == "OPSQ2000" and "없는 종목" in str(error.value)
    assert client.calls == 1


def test_the_same_request_is_answered_from_the_cache_within_its_ttl() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock)

    for _ in range(3):
        client.get(PATH, "X", PARAMS, ttl=30)
    assert client.calls == 1

    clock.monotonic += 31
    client.get(PATH, "X", PARAMS, ttl=30)
    assert client.calls == 2

    client.get(PATH, "X", PARAMS)  # no ttl: never cached
    client.get(PATH, "X", PARAMS)
    assert client.calls == 4


def test_different_parameters_are_different_requests() -> None:
    server, clock = FakeKis(), Clock()
    client = make(server, clock)

    client.get(PATH, "X", {"FID_INPUT_ISCD": "1"}, ttl=30)
    client.get(PATH, "X", {"FID_INPUT_ISCD": "2"}, ttl=30)

    assert client.calls == 2


def test_nothing_secret_ends_up_in_what_the_client_logs(caplog: pytest.LogCaptureFixture) -> None:
    server, clock = FakeKis(), Clock()
    caplog.set_level("DEBUG")
    server.failures = [
        lambda: httpx.Response(
            200, json={"rt_cd": "1", "msg_cd": "X", "msg1": f"bad {KEY} {SECRET}"}
        )
    ]

    with pytest.raises(KisApiError) as error:
        make(server, clock).get(PATH, "X", PARAMS)

    shown = str(error.value) + caplog.text + json.dumps([r.getMessage() for r in caplog.records])
    assert "tok-abcdef" not in shown
    del shown
