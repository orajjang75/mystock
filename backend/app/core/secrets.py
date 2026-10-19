"""Keep server-side secrets out of logs and API responses (PRD 10장 보안).

Secrets exist only as environment variables. ``redact`` replaces every configured secret value
in a piece of text; ``install_log_redaction`` applies it to every log record, so a secret that
slips into an exception message (for example a request URL carrying a bot token) never reaches
the log output.
"""

import logging
from collections.abc import Iterable

from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings

MASK = "***"
_MIN_LENGTH = 4  # shorter values would also mangle ordinary words

# Secrets that only exist at run time, such as the access token a broker hands out. Everything
# below masks them too, once added.
_runtime: set[str] = set()


def add_runtime_secret(value: str) -> None:
    """Mask ``value`` from now on in logs and error messages."""
    if len(value) >= _MIN_LENGTH:
        _runtime.add(value)


def forget_runtime_secrets() -> None:
    _runtime.clear()


def secret_values(settings: Settings) -> list[str]:
    """Every configured value that must never be shown, longest first."""
    candidates: list[str | None] = []
    for value in (
        settings.app_password,
        settings.secret_key,
        settings.krx_pw,
        settings.kis_app_key,
        settings.kis_app_secret,
        settings.telegram_bot_token,
    ):
        candidates.append(value.get_secret_value() if isinstance(value, SecretStr) else None)
    try:
        candidates.append(make_url(settings.database_url).password)
    except Exception:  # an unparsable URL has no password we could mask separately
        candidates.append(None)
    found = {c for c in [*candidates, *_runtime] if c and len(c) >= _MIN_LENGTH}
    return sorted(found, key=len, reverse=True)


def redact(text: str, secrets: Iterable[str] | None = None) -> str:
    """``text`` with every secret value replaced by ``***``."""
    for secret in secrets if secrets is not None else secret_values(get_settings()):
        text = text.replace(secret, MASK)
    return text


class RedactingFilter(logging.Filter):
    """Mask secrets in the message and arguments of every log record."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = list(secrets)

    def _current(self) -> list[str]:
        return sorted({*self._secrets, *_runtime}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = self._current()
        message = record.getMessage()
        if any(secret in message for secret in secrets):
            record.msg = redact(message, secrets)
            record.args = None
        if record.exc_info:
            trace = logging.Formatter().formatException(record.exc_info)
            if any(secret in trace for secret in secrets):
                record.exc_text = redact(trace, secrets)  # handlers print exc_text as is
        return True


def install_log_redaction(settings: Settings | None = None) -> None:
    """Attach the redacting filter to the root logger's handlers (idempotent)."""
    secrets = secret_values(settings or get_settings())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter(secrets))
