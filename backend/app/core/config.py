from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Server settings. Secrets come from environment variables only (PRD 10장 보안)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str
    app_username: str
    app_password: SecretStr
    secret_key: SecretStr = Field(min_length=32)
    adapter: Literal["mock", "pykrx", "kis"] = "mock"
    cookie_secure: bool = False
    universe_include_preferred: bool = False
    mock_seed: int = 42
    # When the daily scan may start. Placeholder until the time KRX finalizes investor flow data
    # is decided (PRD 10장 오픈 이슈).
    daily_scan_time: time = time(18, 0)
    # KRX data-portal login, required by pykrx (>= 1.2). Server-side only, never logged.
    krx_id: str | None = None
    krx_pw: SecretStr | None = None
    # Broker and notification secrets: environment variables only, never logged or returned.
    kis_app_key: SecretStr | None = None
    kis_app_secret: SecretStr | None = None
    kis_env: Literal["real", "paper"] = "real"  # 실전 or 모의투자 server of the KIS Open API
    # Requests per second to KIS. None: 10 on the real server (KIS allows about 20) and 2 on the
    # paper server. Keep it well below the limit: going over only costs a retry, a ban a day.
    kis_max_rps: float | None = Field(default=None, gt=0)
    kis_base_url: str | None = None  # override the server of ``kis_env`` (tests, proxies)
    # The access token is valid for a day and may be issued once a minute, so it is kept in a
    # file (mode 600) to survive restarts. Empty: keep it in memory only.
    kis_token_file: str | None = "~/.mystock/kis_token.json"
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    # 모의 운영 (PRD 로드맵 5단계): real market data, signals and alerts, but no fills are accepted.
    paper_run: bool = False
    # Run the APScheduler jobs inside the API process (one worker only).
    scheduler_enabled: bool = False
    session_max_age_seconds: int = 60 * 60 * 24 * 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
