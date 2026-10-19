"""HTTP client of the 한국투자증권 (KIS) Open API: token, rate limit, response cache, retries.

What it knows about the service (from KIS's own sample code, github.com/koreainvestment/
open-trading-api, and its API portal):

- ``POST /oauth2/tokenP`` with the app key and secret returns an access token valid for a day;
  asking again within a minute is refused, and within six hours returns the same token.
- Every request carries ``authorization``, ``appkey``, ``appsecret`` and ``tr_id`` headers.
- The real server allows about 20 requests per second per app key and the paper server about 2;
  going over answers ``msg_cd = EGW00201`` (sometimes HTTP 429).
- A successful reply has ``rt_cd == "0"``; anything else has ``msg_cd`` and ``msg1``.

Keys come from the environment only. The access token is registered as a secret, so it is masked
in logs and error messages like the keys are, and it is kept in a mode-600 file between restarts.

Not yet run against the live service (no keys were available while writing this); the behaviour
is covered by tests against a fake server that answers as documented.
"""

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.market import KST
from app.core.secrets import add_runtime_secret, redact

logger = logging.getLogger(__name__)

BASE_URLS = {
    "real": "https://openapi.koreainvestment.com:9443",
    "paper": "https://openapivts.koreainvestment.com:29443",
}
DEFAULT_RPS = {"real": 10.0, "paper": 2.0}
TOKEN_MARGIN = timedelta(minutes=10)  # renew before it actually runs out
TOKEN_MIN_INTERVAL = timedelta(seconds=61)  # KIS: one issue per minute
RATE_LIMIT_CODES = {"EGW00201"}  # 초당 거래건수 초과
EXPIRED_TOKEN_CODES = {"EGW00123", "EGW00121"}  # 기간이 만료된 token / 유효하지 않은 token
RETRY_STATUSES = {429, 500, 502, 503, 504}


class KisError(RuntimeError):
    """Base class of the errors below; the message never contains a secret."""


class KisAuthError(KisError):
    """The token could not be issued (bad keys, or asked again within a minute)."""


class KisApiError(KisError):
    """KIS answered with ``rt_cd != "0"``."""

    def __init__(self, msg_cd: str, message: str) -> None:
        super().__init__(f"KIS {msg_cd}: {message}")
        self.msg_cd = msg_cd


class KisUnavailableError(KisError):
    """The service did not answer (network, timeout, 5xx) even after the retries."""


class RateLimiter:
    """At most ``rps`` requests per second, shared by every thread using the client."""

    def __init__(
        self,
        rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = 1.0 / rps
        self._clock, self._sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            self._sleep(wait)


@dataclass
class Token:
    value: str
    expires_at: datetime
    issued_at: datetime

    def usable(self, now: datetime) -> bool:
        return now + TOKEN_MARGIN < self.expires_at


class TokenFile:
    """The token kept between restarts. Tied to the key and the server so a changed key or a
    switch from paper to real never reuses a token that belongs to another account."""

    def __init__(self, path: str | None, env: str, app_key: str) -> None:
        self._path = Path(path).expanduser() if path else None
        self._tag = f"{env}:{hashlib.sha256(app_key.encode()).hexdigest()[:16]}"

    def load(self) -> Token | None:
        if self._path is None or not self._path.exists():
            return None
        try:
            saved = json.loads(self._path.read_text())
            if saved.get("tag") != self._tag:
                return None
            return Token(
                saved["access_token"],
                datetime.fromisoformat(saved["expires_at"]),
                datetime.fromisoformat(saved["issued_at"]),
            )
        except (OSError, ValueError, KeyError):
            return None

    def save(self, token: Token) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "tag": self._tag,
                    "access_token": token.value,
                    "expires_at": token.expires_at.isoformat(),
                    "issued_at": token.issued_at.isoformat(),
                }
            )
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
        except OSError as error:  # not fatal: the next start just asks for a token again
            logger.warning("could not save the KIS token file: %s", type(error).__name__)

    def clear(self) -> None:
        if self._path is not None:
            self._path.unlink(missing_ok=True)


class KisClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        *,
        env: str = "real",
        base_url: str | None = None,
        max_rps: float | None = None,
        token_file: str | None = None,
        http: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(KST),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        retries: int = 3,
        backoff: float = 0.5,
    ) -> None:
        self._key, self._secret = app_key, app_secret
        add_runtime_secret(app_key)  # masked even if the settings do not list them
        add_runtime_secret(app_secret)
        self._base = (base_url or BASE_URLS[env]).rstrip("/")
        self._http = http or httpx.Client(timeout=httpx.Timeout(10.0))
        self._now, self._sleep = now, sleep
        self._limiter = RateLimiter(max_rps or DEFAULT_RPS[env], clock, sleep)
        self._retries, self._backoff = retries, backoff
        self._files = TokenFile(token_file, env, app_key)
        self._token: Token | None = None
        self._last_issue: datetime | None = None
        self._token_lock = threading.Lock()
        self._cache: dict[
            tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict[str, Any]]
        ] = {}
        self._cache_lock = threading.Lock()
        self._clock = clock
        self.calls = 0  # requests sent, for the tests and the operations report

    # --- token ---------------------------------------------------------------------------------

    def _use(self, token: Token) -> Token:
        add_runtime_secret(token.value)
        self._token = token
        return token

    def _ensure_token(self) -> str:
        with self._token_lock:
            now = self._now()
            if self._token and self._token.usable(now):
                return self._token.value
            saved = self._files.load()
            if saved and saved.usable(now):
                return self._use(saved).value
            if self._last_issue and now - self._last_issue < TOKEN_MIN_INTERVAL:
                raise KisAuthError("KIS issues a token once a minute; try again shortly")
            self._last_issue = now
            return self._use(self._issue(now)).value

    def _issue(self, now: datetime) -> Token:
        try:
            response = self._http.post(
                f"{self._base}/oauth2/tokenP",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self._key,
                    "appsecret": self._secret,
                },
            )
        except httpx.HTTPError as error:
            raise KisAuthError(f"token request failed: {type(error).__name__}") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        value = data.get("access_token")
        if response.status_code != 200 or not value:
            code = data.get("error_code") or data.get("msg_cd") or response.status_code
            text = data.get("error_description") or data.get("msg1") or "token was refused"
            raise KisAuthError(redact(f"token was refused ({code}): {text}"))
        seconds = int(data.get("expires_in") or 86400)
        token = Token(value, now + timedelta(seconds=seconds), now)
        self._files.save(token)
        return token

    def _drop_token(self) -> None:
        with self._token_lock:
            self._token = None
            self._files.clear()

    # --- requests ------------------------------------------------------------------------------

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self._key,
            "appsecret": self._secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def get(
        self, path: str, tr_id: str, params: dict[str, str], *, ttl: float = 0.0
    ) -> dict[str, Any]:
        """One GET, within the rate limit, retried on rate-limit and server trouble.

        ``ttl`` seconds: an identical request is answered from the cache. Use a long ttl for data
        that cannot change any more (a past day's bars) and a few seconds for today's, so a tick
        that asks twice does not pay twice.
        """
        key = (path, tuple(sorted(params.items())))
        if ttl > 0:
            with self._cache_lock:
                hit = self._cache.get(key)
            if hit and hit[0] > self._clock():
                return hit[1]
        body = self._send(path, tr_id, params)
        if ttl > 0:
            with self._cache_lock:
                self._cache[key] = (self._clock() + ttl, body)
                if len(self._cache) > 5000:  # drop what has expired, then the oldest
                    now = self._clock()
                    self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        return body

    def _send(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, Any]:
        refreshed = False
        last = "no answer"
        for attempt in range(self._retries + 1):
            self._limiter.acquire()
            self.calls += 1
            try:
                response = self._http.get(
                    self._base + path, params=params, headers=self._headers(tr_id)
                )
            except httpx.HTTPError as error:
                last = type(error).__name__
                self._wait(attempt)
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            code = str(body.get("msg_cd", ""))
            if response.status_code == 200 and body.get("rt_cd") == "0":
                return dict(body)
            if code in EXPIRED_TOKEN_CODES or response.status_code == 401:
                if refreshed:
                    raise KisAuthError(redact(f"the token was refused again ({code or 401})"))
                refreshed = True
                self._drop_token()
                continue
            if code in RATE_LIMIT_CODES or response.status_code in RETRY_STATUSES:
                last = code or f"HTTP {response.status_code}"
                self._wait(attempt, slow=code in RATE_LIMIT_CODES)
                continue
            raise KisApiError(
                code or f"HTTP {response.status_code}", redact(str(body.get("msg1", "")))
            )
        raise KisUnavailableError(
            f"KIS did not answer {path} after {self._retries + 1} tries ({last})"
        )

    def _wait(self, attempt: int, *, slow: bool = False) -> None:
        # 0.5 s, 1 s, 2 s ...; a rate-limit answer waits a full second at least
        self._sleep(max(self._backoff * 2**attempt, 1.0 if slow else 0.0))
