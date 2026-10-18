import io
import logging

import pytest

from app.core.config import Settings
from app.core.secrets import MASK, RedactingFilter, install_log_redaction, redact, secret_values

TOKEN = "123456789:AAH-super-secret-token"


def settings_with_secrets() -> Settings:
    return Settings(
        telegram_bot_token=TOKEN,
        telegram_chat_id="42",
        kis_app_key="kis-key-0001",
        kis_app_secret="kis-secret-0002",
        krx_pw="krx-password",
        database_url="postgresql+psycopg://mystock:db-password-77@localhost/mystock",
    )


def test_every_configured_secret_is_collected() -> None:
    values = secret_values(settings_with_secrets())

    for secret in (TOKEN, "kis-key-0001", "kis-secret-0002", "krx-password", "db-password-77"):
        assert secret in values
    assert "42" not in values  # the chat id is not a secret
    assert values == sorted(values, key=len, reverse=True)


def test_redact_masks_each_secret_wherever_it_appears() -> None:
    secrets = secret_values(settings_with_secrets())
    text = f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed; key=kis-key-0001"

    result = redact(text, secrets)

    assert TOKEN not in result
    assert "kis-key-0001" not in result
    assert result.count(MASK) == 2
    assert "api.telegram.org" in result  # the rest of the message stays readable


def test_settings_never_print_their_secrets() -> None:
    shown = repr(settings_with_secrets()) + str(settings_with_secrets())

    assert TOKEN not in shown
    assert "kis-secret-0002" not in shown


def test_the_log_filter_masks_messages_arguments_and_tracebacks() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter(secret_values(settings_with_secrets())))
    logger = logging.getLogger("secrets-test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("token is %s", TOKEN)
        logger.info("literal %s" % "kis-key-0001")  # noqa: UP031
        try:
            raise RuntimeError(f"connect to https://x/bot{TOKEN}/y failed")
        except RuntimeError:
            logger.exception("request failed")
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert TOKEN not in output
    assert "kis-key-0001" not in output
    assert "request failed" in output  # the log line itself is still there
    assert "RuntimeError" in output


def test_install_attaches_the_filter_once_to_the_root_handlers() -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        install_log_redaction(settings_with_secrets())
        install_log_redaction(settings_with_secrets())

        assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
    finally:
        root.removeHandler(handler)


@pytest.mark.parametrize("secret", ["", "abc"])
def test_values_that_are_too_short_are_left_out(secret: str) -> None:
    settings = Settings(app_password=secret)

    assert secret not in secret_values(settings)
