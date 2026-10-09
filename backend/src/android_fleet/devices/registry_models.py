"""Persistent configuration contracts, independent of API and SQLite adapters."""

from dataclasses import dataclass, field
from datetime import datetime

from android_fleet.devices.models import ConnectionType


@dataclass(frozen=True)
class DeviceRegistration:
    name: str
    connection_type: ConnectionType
    host: str | None = None
    port: int | None = None
    serial: str | None = None
    mdns_service: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    auto_connect: bool = True


@dataclass(frozen=True)
class RegisteredDevice:
    id: str
    name: str
    connection_type: ConnectionType
    host: str | None
    port: int | None
    serial: str | None
    mdns_service: str | None
    metadata: dict[str, str]
    auto_connect: bool
    created_at: datetime
    updated_at: datetime
    last_connected_at: datetime | None = None

    @property
    def address(self) -> str | None:
        if self.host is None or self.port is None:
            return None
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"
