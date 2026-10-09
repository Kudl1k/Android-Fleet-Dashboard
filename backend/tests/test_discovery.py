from datetime import UTC, datetime

import pytest

from android_fleet.adb.connection_models import ConnectionObservation
from android_fleet.adb.fake import FakeAdbClient
from android_fleet.devices.models import ConnectionType, DeviceState
from android_fleet.devices.registry_models import RegisteredDevice
from android_fleet.discovery.models import DiscoverySnapshot, MdnsService
from android_fleet.discovery.service import DiscoveryError, DiscoveryService, discovered_devices


class DiscoveryAdb(FakeAdbClient):
    mdns_calls = 0

    async def mdns_services(self) -> tuple[MdnsService, ...]:
        self.mdns_calls += 1
        raise RuntimeError("private diagnostic")


async def test_optional_mdns_does_not_break_transport_listing() -> None:
    adb = DiscoveryAdb()
    disabled = await DiscoveryService(adb).scan()
    assert disabled.transports == adb.devices
    assert not disabled.mdns_available
    assert adb.mdns_calls == 0
    unavailable = await DiscoveryService(adb, enable_mdns=True).scan()
    assert unavailable.transports == adb.devices
    assert unavailable.services == ()
    assert not unavailable.mdns_available
    assert adb.mdns_calls == 1
    assert not adb.calls


async def test_listing_failure_is_safe_and_not_an_empty_fleet() -> None:
    class BrokenAdb(DiscoveryAdb):
        async def list_devices(self) -> dict[str, DeviceState]:
            raise OSError("sensitive internal path")

    with pytest.raises(DiscoveryError, match="ADB device enumeration unavailable") as error:
        await DiscoveryService(BrokenAdb()).scan()
    assert "sensitive" not in str(error.value)


async def test_successful_mdns_scan() -> None:
    service = MdnsService("pixel._adb-tls-connect._tcp", "_adb-tls-connect._tcp", "10.0.0.1", 40000)

    class AvailableAdb(DiscoveryAdb):
        async def mdns_services(self) -> tuple[MdnsService, ...]:
            return (service,)

    snapshot = await DiscoveryService(AvailableAdb(), enable_mdns=True).scan()
    assert snapshot.mdns_available
    assert snapshot.services == (service,)


def config(*, serial: str | None = None, service: str | None = None) -> RegisteredDevice:
    now = datetime.now(UTC)
    return RegisteredDevice(
        id="registered",
        name="Pixel",
        connection_type=ConnectionType.WIRELESS_ADB,
        host="10.0.0.1",
        port=5555,
        serial=serial,
        mdns_service=service,
        metadata={},
        auto_connect=True,
        created_at=now,
        updated_at=now,
    )


def test_transports_match_exact_registered_or_observed_serial() -> None:
    snapshot = DiscoverySnapshot(
        {"observed": DeviceState.ONLINE, "other": DeviceState.UNAUTHORIZED}
    )
    observations = {
        "registered": ConnectionObservation("registered", DeviceState.ONLINE, "observed")
    }
    rows = discovered_devices(snapshot, [config()], observations)
    assert rows[0].registered_device_id == "registered"
    assert rows[1].registered_device_id is None
    assert rows[1].state == DeviceState.UNAUTHORIZED


def test_mdns_exact_service_matches_dynamic_port_and_never_host_only() -> None:
    name = "pixel._adb-tls-connect._tcp"
    services = (
        MdnsService(name, "_adb-tls-connect._tcp", "10.0.0.1", 40000),
        MdnsService("other._adb-tls-connect._tcp", "_adb-tls-connect._tcp", "10.0.0.1", 40001),
    )
    rows = discovered_devices(DiscoverySnapshot({}, services, True), [config(service=name)], {})
    assert rows[0].registered_device_id == "registered"
    assert rows[0].state == DeviceState.OFFLINE
    assert rows[1].registered_device_id is None


def test_pairing_service_remains_distinct_from_online_transport() -> None:
    address = "10.0.0.1:40000"
    connect = MdnsService("pixel._adb-tls-connect._tcp", "_adb-tls-connect._tcp", "10.0.0.1", 40000)
    pairing = MdnsService("pixel._adb-tls-pairing._tcp", "_adb-tls-pairing._tcp", "10.0.0.1", 40000)
    snapshot = DiscoverySnapshot({address: DeviceState.ONLINE}, (connect, pairing, connect), True)
    rows = discovered_devices(snapshot, [config(service=connect.name)], {})
    assert len(rows) == 2
    assert rows[0].state == DeviceState.ONLINE
    assert rows[0].registered_device_id == "registered"
    assert rows[1].state == DeviceState.PAIRING_REQUIRED
    assert rows[1].registered_device_id is None


def test_configured_address_and_usb_serial_match_exactly() -> None:
    registered = config(serial="usb-serial")
    rows = discovered_devices(
        DiscoverySnapshot({"10.0.0.1:5555": DeviceState.OFFLINE, "usb-serial": DeviceState.ONLINE}),
        [registered],
        {},
    )
    assert all(row.registered_device_id == "registered" for row in rows)
