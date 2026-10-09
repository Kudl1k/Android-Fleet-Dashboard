"""Versioned transport models; configuration validation also lives in the registry."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from android_fleet.devices.models import ConnectionType, DeviceCapability, DeviceState
from android_fleet.devices.registry_models import DeviceRegistration


class DeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    connection_type: ConnectionType
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535, strict=True)
    serial: str | None = None
    mdns_service: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    auto_connect: bool = Field(default=True, strict=True)

    def registration(self) -> DeviceRegistration:
        return DeviceRegistration(**self.model_dump())


class DevicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    connection_type: ConnectionType | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535, strict=True)
    serial: str | None = None
    mdns_service: str | None = None
    metadata: dict[str, str] | None = None
    auto_connect: bool | None = Field(default=None, strict=True)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    serial: str
    name: str
    state: DeviceState
    connection_type: ConnectionType
    manufacturer: str | None
    model: str | None
    android_version: str | None
    sdk: int | None
    abi: str | None
    soc: str | None
    root_available: bool | None
    capabilities: set[DeviceCapability]
    last_seen: datetime | None
    host: str | None = None
    port: int | None = None
    mdns_service: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    auto_connect: bool = Field(default=True, strict=True)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_connected_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_in_seconds: float | None = None
