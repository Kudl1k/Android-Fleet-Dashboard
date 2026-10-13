"""Transport-independent screen configuration and validated input contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionState(StrEnum):
    STARTING = "starting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ScreenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_size: int = Field(default=1280, ge=320, le=2560)
    max_fps: int = Field(default=30, ge=1, le=60)
    bitrate: int = Field(default=4_000_000, ge=100_000, le=12_000_000)
    codec: Literal["h264"] = "h264"


class InputEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["pointer", "key", "text", "nav"]
    action: Literal["down", "move", "up", "cancel"] | None = None
    x: int | None = Field(default=None, ge=0, le=65535)
    y: int | None = Field(default=None, ge=0, le=65535)
    width: int | None = Field(default=None, ge=1, le=65535)
    height: int | None = Field(default=None, ge=1, le=65535)
    pressure: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    buttons: int = Field(default=1, ge=0, le=7)
    keycode: int | None = None
    repeat: int = Field(default=0, ge=0, le=1)
    meta: int = Field(default=0, ge=0, le=65535)
    text: str | None = Field(default=None, min_length=1, max_length=300)
    key: Literal["back", "home", "recent", "wake", "volume_up", "volume_down"] | None = None

    @model_validator(mode="after")
    def valid_event(self) -> "InputEvent":
        groups = {
            "pointer": {"action", "x", "y", "width", "height", "pressure", "buttons"},
            "key": {"action", "keycode", "repeat", "meta"},
            "text": {"text"},
            "nav": {"key"},
        }
        if self.model_fields_set - groups[self.type] - {"type"}:
            raise ValueError("Unexpected input fields")
        if self.type == "pointer":
            if any(v is None for v in (self.action, self.x, self.y, self.width, self.height)):
                raise ValueError("Pointer position and dimensions required")
            assert self.x is not None and self.y is not None
            assert self.width is not None and self.height is not None
            if self.x >= self.width or self.y >= self.height:
                raise ValueError("Pointer outside display")
        elif self.type == "key":
            if self.action not in {"down", "up"} or self.keycode not in {
                4,
                19,
                20,
                21,
                22,
                23,
                57,
                58,
                59,
                60,
                61,
                62,
                66,
                67,
                111,
                112,
                113,
                114,
                122,
                123,
            }:
                raise ValueError("Unsupported keyboard event")
        elif self.type == "text" and not self.text:
            raise ValueError("Text required")
        elif self.type == "text" and self.text and len(self.text.encode("utf-8")) > 300:
            raise ValueError("Text exceeds protocol limit")
        elif self.type == "nav" and not self.key:
            raise ValueError("Navigation key required")
        return self
