from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import DbSession, require_user
from app.db.enums import BarLength
from app.engine.params import SignalParams
from app.services import settings as service

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_user)])

PresetName = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[^/\\]+$")]


class SettingsDocument(BaseModel):
    """Everything the settings screen edits. ``PUT`` replaces it as a whole."""

    signal_params: SignalParams
    signal_bar_length: BarLength  # A-11: 30m, 60m or 1d
    alert_cooldown_bars: int = Field(ge=0, le=500)  # A-10
    channels: dict[str, bool]  # outside channels switched on (A-12)
    refresh_seconds: int  # polling period of the screen; 0 = off

    @field_validator("refresh_seconds")
    @classmethod
    def _period(cls, seconds: int) -> int:
        if seconds != 0 and not 10 <= seconds <= 3600:
            raise ValueError("refresh_seconds must be 0 (off) or between 10 and 3600")
        return seconds

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, channels: dict[str, bool]) -> dict[str, bool]:
        unknown = set(channels) - set(service.CHANNEL_NAMES)
        if unknown:
            raise ValueError(f"Unknown channel: {', '.join(sorted(unknown))}")
        return channels


class PresetInfo(BaseModel):
    name: str
    updated_at: datetime


class SettingsResponse(SettingsDocument):
    presets: list[PresetInfo]


class PresetCreate(BaseModel):
    name: PresetName


def _response(db: DbSession) -> SettingsResponse:
    return SettingsResponse(
        signal_params=service.load_signal_params(db),
        signal_bar_length=service.load_signal_bar_length(db),
        alert_cooldown_bars=service.load_alert_cooldown_bars(db),
        channels=service.load_channels(db),
        refresh_seconds=service.load_refresh_seconds(db),
        presets=[PresetInfo(name=n, updated_at=t) for n, t in service.list_presets(db)],
    )


@router.get("")
def get_settings(db: DbSession) -> SettingsResponse:
    """The current settings and the names of the saved presets."""
    return _response(db)


@router.put("")
def put_settings(body: SettingsDocument, db: DbSession) -> SettingsResponse:
    """Replace the current settings."""
    service.save_signal_params(db, body.signal_params)
    service.save_signal_bar_length(db, body.signal_bar_length)
    service.save_alert_cooldown_bars(db, body.alert_cooldown_bars)
    service.save_channels(db, body.channels)
    service.save_refresh_seconds(db, body.refresh_seconds)
    db.commit()
    return _response(db)


@router.post("/presets", status_code=status.HTTP_201_CREATED)
def save_preset(body: PresetCreate, db: DbSession) -> PresetInfo:
    """Save the current parameters, bar length and cooldown as a preset (same name: replaced)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The name is empty")
    service.save_preset(db, name)
    db.commit()
    saved = dict(service.list_presets(db))
    return PresetInfo(name=name, updated_at=saved[name])


@router.post("/presets/{name}/load")
def load_preset(name: str, db: DbSession) -> SettingsResponse:
    """Make a preset the current settings (channels and the polling period are kept)."""
    if not service.load_preset(db, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No preset named {name}")
    db.commit()
    return _response(db)


@router.delete("/presets/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(name: str, db: DbSession) -> Response:
    if not service.delete_preset(db, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No preset named {name}")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
