"""Stored user settings: signal parameters and bar length (more with the settings screen)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import BarLength
from app.db.models import Setting
from app.engine.params import SignalParams

CURRENT = "current"
_PARAMS = "signal_params"
_BAR_LENGTH = "signal_bar_length"
DEFAULT_BAR_LENGTH = BarLength.M60  # A-11


def _value(session: Session) -> dict[str, Any]:
    row = session.get(Setting, CURRENT)
    return dict(row.value) if row else {}


def _store(session: Session, key: str, value: Any) -> None:
    """Set one key of the current settings, keeping the others. Flushes, does not commit."""
    merged = {**_value(session), key: value}
    row = session.get(Setting, CURRENT)
    if row is None:
        session.add(Setting(name=CURRENT, value=merged))
    else:
        row.value = merged
    session.flush()


def load_signal_params(session: Session) -> SignalParams:
    """The saved signal parameters, or the PRD defaults if none were saved."""
    saved = _value(session).get(_PARAMS)
    return SignalParams.model_validate(saved) if saved else SignalParams()


def save_signal_params(session: Session, params: SignalParams) -> None:
    _store(session, _PARAMS, params.model_dump(mode="json"))


def load_signal_bar_length(session: Session) -> BarLength:
    """A-11: the bar length alerts are computed on (30m, 60m or 1d; default 60m)."""
    saved = _value(session).get(_BAR_LENGTH)
    return BarLength(saved) if saved else DEFAULT_BAR_LENGTH


def save_signal_bar_length(session: Session, length: BarLength) -> None:
    _store(session, _BAR_LENGTH, length.value)


_COOLDOWN = "alert_cooldown_bars"
_CHANNELS = "notification_channels"
DEFAULT_COOLDOWN_BARS = 6  # placeholder: PRD A-10 says "정해진 봉 수" without a number
CHANNEL_NAMES = ("telegram",)


def load_alert_cooldown_bars(session: Session) -> int:
    """A-10: how many signal bars the same signal on the same stock stays quiet."""
    saved = _value(session).get(_COOLDOWN)
    return int(saved) if saved is not None else DEFAULT_COOLDOWN_BARS


def save_alert_cooldown_bars(session: Session, bars: int) -> None:
    if bars < 0:
        raise ValueError("The cooldown cannot be negative")
    _store(session, _COOLDOWN, bars)


def load_channels(session: Session) -> dict[str, bool]:
    """A-12: which outside channels are switched on (all off until the user enables them)."""
    saved = _value(session).get(_CHANNELS) or {}
    return {name: bool(saved.get(name, False)) for name in CHANNEL_NAMES}


def save_channels(session: Session, channels: dict[str, bool]) -> None:
    unknown = set(channels) - set(CHANNEL_NAMES)
    if unknown:
        raise ValueError(f"Unknown channel: {', '.join(sorted(unknown))}")
    _store(session, _CHANNELS, {**load_channels(session), **channels})


_REFRESH = "refresh_seconds"
DEFAULT_REFRESH_SECONDS = 60  # PRD 7장: polling every 60 seconds unless switched off
PRESET_PREFIX = "preset:"


def load_refresh_seconds(session: Session) -> int:
    """How often the screen polls the API, in seconds; 0 means polling is off."""
    saved = _value(session).get(_REFRESH)
    return int(saved) if saved is not None else DEFAULT_REFRESH_SECONDS


def save_refresh_seconds(session: Session, seconds: int) -> None:
    _store(session, _REFRESH, seconds)


# --- presets: named snapshots of the tunable settings ---------------------------------------


def snapshot(session: Session) -> dict[str, Any]:
    """The part of the settings a preset stores: parameters, bar length, cooldown."""
    return {
        _PARAMS: load_signal_params(session).model_dump(mode="json"),
        _BAR_LENGTH: load_signal_bar_length(session).value,
        _COOLDOWN: load_alert_cooldown_bars(session),
    }


def save_preset_values(
    session: Session, name: str, params: SignalParams, bar_length: BarLength
) -> None:
    """Store a preset made of the given parameters and bar length (the cooldown stays as set).

    Used to keep the parameters of a backtest run. The current settings are not touched.
    """
    value = {
        _PARAMS: params.model_dump(mode="json"),
        _BAR_LENGTH: bar_length.value,
        _COOLDOWN: load_alert_cooldown_bars(session),
    }
    key = PRESET_PREFIX + name
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(name=key, value=value, is_preset=True))
    else:
        row.value = value
    session.flush()


def list_presets(session: Session) -> list[tuple[str, datetime]]:
    """(name, last saved) of every preset, by name."""
    rows = session.execute(
        select(Setting.name, Setting.updated_at)
        .where(Setting.is_preset.is_(True))
        .order_by(Setting.name)
    )
    return [(name.removeprefix(PRESET_PREFIX), updated) for name, updated in rows]


def save_preset(session: Session, name: str) -> None:
    """Store the current tunable settings under ``name`` (replacing a preset of that name)."""
    key = PRESET_PREFIX + name
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(name=key, value=snapshot(session), is_preset=True))
    else:
        row.value = snapshot(session)
    session.flush()


def load_preset(session: Session, name: str) -> bool:
    """Make a preset the current settings. ``False`` if there is no such preset."""
    row = session.get(Setting, PRESET_PREFIX + name)
    if row is None:
        return False
    saved = row.value
    save_signal_params(session, SignalParams.model_validate(saved[_PARAMS]))
    save_signal_bar_length(session, BarLength(saved[_BAR_LENGTH]))
    save_alert_cooldown_bars(session, int(saved[_COOLDOWN]))
    return True


def delete_preset(session: Session, name: str) -> bool:
    row = session.get(Setting, PRESET_PREFIX + name)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
