from dataclasses import dataclass

from android_fleet.devices.models import DeviceState


@dataclass(frozen=True)
class MdnsService:
    name: str
    service_type: str
    host: str
    port: int

    @property
    def address(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


@dataclass(frozen=True)
class DiscoveredDevice:
    serial: str
    state: DeviceState
    host: str | None = None
    port: int | None = None
    mdns_service: str | None = None
    service_type: str | None = None
    registered_device_id: str | None = None


@dataclass(frozen=True)
class DiscoverySnapshot:
    transports: dict[str, DeviceState]
    services: tuple[MdnsService, ...] = ()
    mdns_available: bool = False
