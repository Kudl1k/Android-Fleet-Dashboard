"""Read-only discovery; persistent registration and connection policy stay separate."""

from collections.abc import Mapping, Sequence

from android_fleet.adb.base import AdbClient
from android_fleet.adb.connection_models import ConnectionObservation
from android_fleet.devices.models import DeviceState
from android_fleet.devices.registry_models import RegisteredDevice
from android_fleet.discovery.models import DiscoveredDevice, DiscoverySnapshot


class DiscoveryError(RuntimeError):
    """Safe public error without command output or environment details."""


class DiscoveryService:
    def __init__(self, adb: AdbClient, *, enable_mdns: bool = False) -> None:
        self.adb = adb
        self.enable_mdns = enable_mdns

    async def scan(self) -> DiscoverySnapshot:
        try:
            transports = await self.adb.list_devices()
        except (OSError, TimeoutError, RuntimeError) as error:
            raise DiscoveryError("ADB device enumeration unavailable") from error
        if not self.enable_mdns:
            return DiscoverySnapshot(transports)
        try:
            services = await self.adb.mdns_services()
        except (OSError, TimeoutError, RuntimeError):
            return DiscoverySnapshot(transports)
        return DiscoverySnapshot(transports, services, mdns_available=True)


def discovered_devices(
    snapshot: DiscoverySnapshot,
    configs: Sequence[RegisteredDevice],
    observations: Mapping[str, ConnectionObservation],
) -> list[DiscoveredDevice]:
    """Associate exact identities only; never infer ownership from host proximity."""
    transport_owners: dict[str, str] = {}
    service_owners: dict[str, str] = {}
    for config in configs:
        observation = observations.get(config.id)
        identities = [config.serial, config.address, observation.serial if observation else None]
        for identity in identities:
            if identity:
                transport_owners.setdefault(identity, config.id)
        if config.mdns_service:
            service_owners.setdefault(config.mdns_service, config.id)

    rows = {
        serial: DiscoveredDevice(serial, state, registered_device_id=transport_owners.get(serial))
        for serial, state in snapshot.transports.items()
    }
    service_rows: list[DiscoveredDevice] = []
    seen: set[tuple[str, str, str]] = set()
    for service in snapshot.services:
        service_identity = (service.name, service.service_type, service.address)
        if service_identity in seen:
            continue
        seen.add(service_identity)
        pairing = service.service_type == "_adb-tls-pairing._tcp"
        owner = service_owners.get(service.name)
        transport = rows.get(service.address) if not pairing else None
        row = DiscoveredDevice(
            serial=service.address,
            state=(
                DeviceState.PAIRING_REQUIRED
                if pairing
                else transport.state
                if transport
                else DeviceState.OFFLINE
            ),
            host=service.host,
            port=service.port,
            mdns_service=service.name,
            service_type=service.service_type,
            registered_device_id=owner or (transport.registered_device_id if transport else None),
        )
        if transport:
            rows[service.address] = row
        else:
            service_rows.append(row)
    return [*rows.values(), *service_rows]
