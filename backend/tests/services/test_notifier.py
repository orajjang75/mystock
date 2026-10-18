import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.services.notifier import (
    Notification,
    Notifier,
    NotifierError,
    TelegramNotifier,
    build_notifiers,
    channel_states,
    register_channel,
)

TOKEN = "123456789:AAH-super-secret-token"


def client_for(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def settings(**kwargs: Any) -> Settings:
    return Settings(**kwargs)


def configured() -> Settings:
    return settings(telegram_bot_token=TOKEN, telegram_chat_id="42")


# --- Telegram -----------------------------------------------------------------------------------


def test_telegram_posts_the_text_to_the_bot_api() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    TelegramNotifier(TOKEN, "42", client_for(handler)).send(Notification("sell", "hello"))

    (request,) = seen
    assert request.method == "POST"
    assert request.url.host == "api.telegram.org"
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert body["chat_id"] == "42"
    assert body["text"] == "hello"


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500])
def test_a_rejected_message_raises_without_the_token(status_code: int) -> None:
    notifier = TelegramNotifier(TOKEN, "42", client_for(lambda r: httpx.Response(status_code)))

    with pytest.raises(NotifierError) as error:
        notifier.send(Notification("sell", "hello"))

    assert str(status_code) in str(error.value)
    assert TOKEN not in str(error.value)


def test_a_network_failure_raises_without_the_url_or_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    notifier = TelegramNotifier(TOKEN, "42", client_for(handler))

    with pytest.raises(NotifierError) as error:
        notifier.send(Notification("sell", "hello"))

    assert TOKEN not in str(error.value)
    assert "api.telegram.org" not in str(error.value)
    assert "ConnectError" in str(error.value)
    assert error.value.__cause__ is None  # the original error carries the URL


def test_a_timeout_is_a_notifier_error_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(NotifierError, match="ReadTimeout"):
        TelegramNotifier(TOKEN, "42", client_for(handler)).send(Notification("sell", "x"))


# --- which channels are used ---------------------------------------------------------------------


def test_a_channel_is_used_only_when_switched_on_and_configured() -> None:
    client = client_for(lambda r: httpx.Response(200))

    assert build_notifiers(configured(), {"telegram": True}, client)[0].name == "telegram"
    assert build_notifiers(configured(), {"telegram": False}, client) == []
    assert build_notifiers(configured(), {}, client) == []
    assert build_notifiers(settings(), {"telegram": True}, client) == []  # no token set


def test_a_missing_chat_id_means_not_configured() -> None:
    assert build_notifiers(settings(telegram_bot_token=TOKEN), {"telegram": True}) == []


def test_an_enabled_but_unconfigured_channel_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    build_notifiers(settings(), {"telegram": True})

    assert "enabled but not configured" in caplog.text


def test_channel_states_report_switches_and_configuration() -> None:
    (state,) = [
        s for s in channel_states(configured(), {"telegram": False}) if s.name == "telegram"
    ]

    assert (state.enabled, state.configured) == (False, True)
    (missing,) = [s for s in channel_states(settings(), {"telegram": True}) if s.name == "telegram"]
    assert (missing.enabled, missing.configured) == (True, False)


def test_a_new_channel_only_needs_a_notifier_and_a_registration() -> None:
    sent: list[str] = []

    class BrowserPush(Notifier):
        name = "browser_push"

        def send(self, notification: Notification) -> None:
            sent.append(notification.text)

    register_channel("browser_push", lambda settings, client: BrowserPush())
    try:
        notifiers = build_notifiers(settings(), {"browser_push": True})
        notifiers[0].send(Notification("sell", "pushed"))
    finally:
        from app.services import notifier

        notifier._FACTORIES.pop("browser_push")

    assert [n.name for n in notifiers] == ["browser_push"]
    assert sent == ["pushed"]
