from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionState(StrEnum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    DISCONNECTING = "disconnecting"
    CLOSED = "closed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class TerminalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_type: Literal["adb", "ssh"]
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    cols: int = Field(default=80, ge=2, le=500)
    rows: int = Field(default=24, ge=2, le=200)

    @model_validator(mode="after")
    def target(self) -> Self:
        if self.connection_type == "adb" and (not self.device_id or self.profile_id):
            raise ValueError("ADB requires only a device ID")
        if self.connection_type == "ssh" and (not self.profile_id or self.device_id):
            raise ValueError("SSH requires only a profile ID")
        return self


class TerminalMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    type: Literal["input", "resize", "close", "heartbeat"]
    data: str | None = Field(default=None, max_length=4096)
    cols: int | None = Field(default=None, ge=2, le=500)
    rows: int | None = Field(default=None, ge=2, le=200)

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported protocol version")
        return value

    @model_validator(mode="after")
    def payload(self) -> Self:
        if self.type == "input":
            if self.data is None or self.cols is not None or self.rows is not None:
                raise ValueError("Invalid input")
        elif self.type == "resize":
            if self.cols is None or self.rows is None or self.data is not None:
                raise ValueError("Invalid resize")
        elif self.data is not None or self.cols is not None or self.rows is not None:
            raise ValueError("Unexpected payload")
        return self
