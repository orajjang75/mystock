"""Outside-the-app notification channels (PRD A-12).

A channel is a ``Notifier``: it gets a short text and sends it, or raises ``NotifierError``.
Telegram is implemented. A browser-push channel only needs another ``Notifier`` subclass and one
``register_channel`` call; nothing else in the alert flow changes. The text is a summary only
(stock, kind, suggested quantity, rebuy target) - never evidence or parameters.

Tokens come from environment variables only. Errors raised here carry no URL, because a
Telegram request URL contains the bot token.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class NotifierError(RuntimeError):
    """Sending failed. The message is safe to log and to show: it never contains a secret."""


@dataclass(frozen=True, slots=True)
class Notification:
    kind: str
    text: str


class Notifier(ABC):
    name: str

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Deliver the notification or raise ``NotifierError``."""


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=timeout)
        self._attempts = attempts
        self._sleep = sleep

    def send(self, notification: Notification) -> None:
        """Send, retrying twice (0.5 s, 1 s) on a network error, HTTP 429 or a server error.

        Telegram's ``Retry-After`` on a 429 is honoured up to five seconds. The last failure is
        reported without a URL, because a Telegram request URL contains the bot token.
        """
        url = f"{TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": notification.text,
            "disable_web_page_preview": True,
        }
        failure = "no attempt"
        for attempt in range(self._attempts):
            try:
                response = self._client.post(url, json=payload)
            except httpx.HTTPError as error:
                failure = f"telegram request failed ({type(error).__name__})"
                self._pause(attempt, None)
                continue
            if response.status_code == httpx.codes.OK:
                return
            failure = f"telegram rejected the message (HTTP {response.status_code})"
            if response.status_code != 429 and response.status_code < 500:
                break  # a bad token or chat id will not get better by asking again
            self._pause(attempt, response.headers.get("retry-after"))
        raise NotifierError(failure)

    def _pause(self, attempt: int, retry_after: str | None) -> None:
        if attempt + 1 >= self._attempts:
            return
        try:
            wait = min(float(retry_after), 5.0) if retry_after else 0.5 * 2**attempt
        except ValueError:
            wait = 0.5 * 2**attempt
        self._sleep(wait)


ChannelFactory = Callable[[Settings, httpx.Client | None], Notifier | None]
_FACTORIES: dict[str, ChannelFactory] = {}


def register_channel(name: str, factory: ChannelFactory) -> None:
    """Add a channel. The factory returns ``None`` when the channel is not configured."""
    _FACTORIES[name] = factory


def _telegram(settings: Settings, client: httpx.Client | None) -> Notifier | None:
    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        return None
    return TelegramNotifier(
        settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id, client
    )


register_channel("telegram", _telegram)


@dataclass(frozen=True, slots=True)
class ChannelState:
    name: str
    enabled: bool  # switched on in the settings
    configured: bool  # its credentials are set in the environment


def channel_states(
    settings: Settings, enabled: dict[str, bool], client: httpx.Client | None = None
) -> list[ChannelState]:
    return [
        ChannelState(name, enabled.get(name, False), factory(settings, client) is not None)
        for name, factory in _FACTORIES.items()
    ]


def build_notifiers(
    settings: Settings, enabled: dict[str, bool], client: httpx.Client | None = None
) -> list[Notifier]:
    """The notifiers that are both switched on and configured."""
    notifiers = []
    for name, factory in _FACTORIES.items():
        if enabled.get(name, False):
            notifier = factory(settings, client)
            if notifier is not None:
                notifiers.append(notifier)
            else:
                logger.warning("channel %s is enabled but not configured", name)
    return notifiers
