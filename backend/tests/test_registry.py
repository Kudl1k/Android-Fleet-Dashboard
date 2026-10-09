import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from android_fleet.devices.models import ConnectionType
from android_fleet.devices.registry import (
    DeviceNotFound,
    DuplicateDevice,
    InvalidRegistration,
    RegistryError,
    SQLiteDeviceRegistry,
)
from android_fleet.devices.registry_models import DeviceRegistration


def network(host: str = "192.168.1.10", port: int = 5555) -> DeviceRegistration:
    return DeviceRegistration("Pixel", ConnectionType.ADB_TCP, host=host, port=port)


async def test_persistence_stable_id_and_configuration_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "registry.sqlite3"
    registry = SQLiteDeviceRegistry(path)
    await registry.initialize()
    device = await registry.create(network())
    assert str(UUID(device.id)) == device.id
    assert device.created_at.tzinfo == UTC
    updated = await registry.update(device.id, replace(network(), host="192.168.1.11"))
    assert updated.id == device.id
    assert updated.created_at == device.created_at
    assert updated.updated_at >= device.updated_at
    connected = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))
    await registry.mark_connected(device.id, connected)
    assert (await registry.get(device.id)).updated_at == updated.updated_at
    await registry.close()
    reopened = SQLiteDeviceRegistry(path)
    await reopened.initialize()
    persisted = await reopened.get(device.id)
    assert persisted.host == "192.168.1.11"
    assert persisted.last_connected_at == connected.astimezone(UTC)
    assert persisted.updated_at == updated.updated_at
    assert await reopened.list() == [persisted]
    await reopened.close()


async def test_memory_lifecycle_delete_and_not_found() -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    with pytest.raises(RegistryError):
        await registry.list()
    await registry.initialize()
    await registry.initialize()
    device = await registry.create(network(), device_id="pixel-rooted")
    assert device.id == "pixel-rooted"
    assert (await registry.set_auto_connect(device.id, False)).auto_connect is False
    await registry.delete(device.id)
    for operation in (
        registry.get(device.id),
        registry.delete(device.id),
        registry.set_auto_connect(device.id, True),
        registry.mark_connected(device.id, datetime.now(UTC)),
        registry.update(device.id, network()),
    ):
        with pytest.raises(DeviceNotFound):
            await operation
    await registry.close()
    await registry.close()
    with pytest.raises(RegistryError):
        await registry.list()


async def test_normalization_and_snapshot_metadata() -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    metadata = {"location": "lab"}
    device = await registry.create(replace(network("ADB.EXAMPLE.COM."), metadata=metadata))
    assert device.host == "adb.example.com"
    assert device.address == "adb.example.com:5555"
    metadata["location"] = "changed"
    assert (await registry.get(device.id)).metadata == {"location": "lab"}
    ipv6 = await registry.create(network("2001:0db8:0:0:0:0:0:1"))
    assert ipv6.host == "2001:db8::1"
    assert ipv6.address == "[2001:db8::1]:5555"
    wireless = await registry.create(
        DeviceRegistration(
            "Wireless",
            ConnectionType.WIRELESS_ADB,
            host="192.168.1.12",
            port=40000,
            mdns_service="adb-Pixel-123._adb-tls-connect._tcp.local.",
        )
    )
    assert wireless.mdns_service == "adb-pixel-123._adb-tls-connect._tcp"
    await registry.close()


async def test_duplicate_endpoints_usb_mdns_and_atomic_rollback() -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    first = await registry.create(network())
    second = await registry.create(network("192.168.1.11"))
    with pytest.raises(DuplicateDevice):
        await registry.create(replace(network(), connection_type=ConnectionType.WIRELESS_ADB))
    with pytest.raises(DuplicateDevice):
        await registry.update(second.id, replace(network(), name="Changed"))
    assert await registry.get(second.id) == second
    with pytest.raises(DuplicateDevice):
        await registry.create(network("192.168.1.12"), device_id=first.id)
    usb = DeviceRegistration("USB", ConnectionType.USB, serial="ABC123")
    await registry.create(usb)
    with pytest.raises(DuplicateDevice):
        await registry.create(usb)
    wireless = DeviceRegistration(
        "Wireless",
        ConnectionType.WIRELESS_ADB,
        host="192.168.1.20",
        port=40000,
        mdns_service="adb-Pixel._adb-tls-connect._tcp",
    )
    await registry.create(wireless)
    with pytest.raises(DuplicateDevice):
        await registry.create(replace(wireless, host="192.168.1.21"))
    assert len(await registry.list()) == 4
    await registry.close()


async def test_concurrent_writers_are_atomic(tmp_path: Path) -> None:
    first = SQLiteDeviceRegistry(tmp_path / "registry.db")
    second = SQLiteDeviceRegistry(tmp_path / "registry.db")
    await asyncio.gather(first.initialize(), second.initialize())
    results = await asyncio.gather(
        *(registry.create(network()) for registry in (first, second, first, second)),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, DuplicateDevice) for result in results) == 3
    assert len(await first.list()) == 1
    await asyncio.gather(first.close(), second.close())


@pytest.mark.parametrize(
    "registration",
    [
        network("http://192.168.1.10"),
        network("--help"),
        network("foo bar"),
        network(" adb.example.com"),
        network("foo;reboot"),
        network("[::1]"),
        network("fe80::1%eth0"),
        network(port=0),
        network(port=65536),
        replace(network(), port=True),
        replace(network(), host=None),
        replace(network(), serial="ABC"),
        replace(network(), name=" "),
        replace(network(), metadata={"private-key": "never persist"}),
        replace(network(), metadata={"a": "x" * 1025}),
        replace(network(), metadata={str(index): "v" for index in range(33)}),
        DeviceRegistration("USB", ConnectionType.USB),
        DeviceRegistration("USB", ConnectionType.USB, serial="--help"),
        DeviceRegistration("USB", ConnectionType.USB, serial="ABC", host="host"),
        replace(network(), mdns_service="adb-Pixel._adb-tls-connect._tcp"),
        DeviceRegistration(
            "Wireless",
            ConnectionType.WIRELESS_ADB,
            host="host",
            port=5555,
            mdns_service="adb-Pixel._adb-tls-pairing._tcp",
        ),
    ],
)
async def test_invalid_registration_does_not_write(registration: DeviceRegistration) -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    with pytest.raises(InvalidRegistration):
        await registry.create(registration)
    assert await registry.list() == []
    await registry.close()


@pytest.mark.parametrize("identifier", ["", ".", "..", "../device", "a/b", "a?b", "a b"])
async def test_invalid_identifiers(identifier: str) -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    with pytest.raises(InvalidRegistration):
        await registry.create(network(), device_id=identifier)
    await registry.close()


async def test_future_schema_is_rejected_without_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")
    registry = SQLiteDeviceRegistry(path)
    with pytest.raises(RegistryError, match="newer"):
        await registry.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    await registry.close()


async def test_cancelled_mutation_drains_before_return_and_close(tmp_path: Path) -> None:
    import threading

    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    registry = SQLiteDeviceRegistry(tmp_path / "registry.db")
    await registry.initialize()

    def blocking_mutation(connection: sqlite3.Connection) -> None:
        entered.set()
        assert release.wait(timeout=5)
        with connection:
            connection.execute("PRAGMA user_version = 1")
        completed.set()

    mutation = asyncio.create_task(registry._run(blocking_mutation))
    assert await asyncio.to_thread(entered.wait, 5)
    mutation.cancel()
    await asyncio.sleep(0)
    assert not mutation.done()
    # Repeated cancellations must not allow SQL to escape the caller's lock lifetime.
    mutation.cancel()
    await asyncio.sleep(0)
    assert not mutation.done()
    closing = asyncio.create_task(registry.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert completed.is_set()
    await closing
    with pytest.raises(RegistryError):
        await registry.list()


async def test_cancelled_initialization_drains_before_close(tmp_path: Path) -> None:
    import threading

    registry = SQLiteDeviceRegistry(tmp_path / "registry.db")
    acquired = threading.Event()
    release = threading.Event()

    def block_registry() -> None:
        with registry._lock:
            acquired.set()
            assert release.wait(timeout=5)

    blocker = asyncio.create_task(asyncio.to_thread(block_registry))
    assert await asyncio.to_thread(acquired.wait, 5)
    initializing = asyncio.create_task(registry.initialize())
    await asyncio.sleep(0)
    initializing.cancel()
    await asyncio.sleep(0)
    assert not initializing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await initializing
    await blocker
    # initialize has finished in its thread despite cancellation; close owns it now.
    assert await registry.list() == []
    await registry.close()
    assert registry._connection is None


async def test_registry_name_length_matches_api_limit() -> None:
    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    with pytest.raises(InvalidRegistration):
        await registry.create(replace(network(), name="a" * 129))
    created = await registry.create(replace(network(), name="a" * 128))
    assert len(created.name) == 128
    await registry.close()


async def test_cancelled_close_still_releases_connection() -> None:
    import threading

    registry = SQLiteDeviceRegistry(":memory:")
    await registry.initialize()
    acquired = threading.Event()
    release = threading.Event()

    def block_registry() -> None:
        with registry._lock:
            acquired.set()
            assert release.wait(timeout=5)

    blocker = asyncio.create_task(asyncio.to_thread(block_registry))
    assert await asyncio.to_thread(acquired.wait, 5)
    closing = asyncio.create_task(registry.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await blocker
    assert registry._connection is None
