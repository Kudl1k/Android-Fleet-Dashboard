import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from android_fleet.adb.connection import ConnectionManager
from android_fleet.adb.fake import FakeAdbClient
from android_fleet.devices.models import ConnectionType, DeviceState
from android_fleet.devices.registry_models import RegisteredDevice
from android_fleet.discovery.models import MdnsService
from android_fleet.execution.models import CommandResult


def registered(**changes: object) -> RegisteredDevice:
    config = RegisteredDevice(
        id="test",
        name="Test",
        connection_type=ConnectionType.ADB_TCP,
        host="192.0.2.1",
        port=5555,
        serial=None,
        mdns_service=None,
        metadata={},
        auto_connect=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return replace(config, **changes)


@pytest.mark.asyncio
async def test_connect_verified_from_authorized_transport() -> None:
    adb = FakeAdbClient()
    manager = ConnectionManager(adb)
    config = registered()
    initial = await manager.connect(config)
    assert initial.state == DeviceState.OFFLINE
    assert initial.error_code == "connection_refused"
    assert "port" in (initial.error_message or "")
    adb.endpoints["192.0.2.1:5555"] = DeviceState.UNAUTHORIZED
    assert (await manager.connect(config)).state == DeviceState.UNAUTHORIZED
    adb.devices.clear()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    assert (await manager.connect(config)).state == DeviceState.ONLINE


@pytest.mark.asyncio
async def test_backoff_bounded_and_manual_connect_bypasses() -> None:
    now = [100.0]
    adb = FakeAdbClient()
    manager = ConnectionManager(
        adb,
        backoff_initial=2,
        backoff_max=5,
        clock=lambda: now[0],
        random_value=lambda: 1,
    )
    config = registered()
    result = (await manager.reconcile([config], {}))[config.id]
    assert result.retry_in_seconds == 2
    assert result.state == DeviceState.OFFLINE
    result = (await manager.reconcile([config], {}))[config.id]
    assert result.state == DeviceState.RECONNECTING
    assert len(adb.connection_calls) == 1
    now[0] += 2
    result = (await manager.reconcile([config], {}))[config.id]
    assert result.retry_in_seconds == 4
    now[0] += 4
    result = (await manager.reconcile([config], {}))[config.id]
    assert result.retry_in_seconds == 5
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    assert (await manager.connect(config)).state == DeviceState.ONLINE
    assert len(adb.connection_calls) == 4


@pytest.mark.asyncio
async def test_concurrent_connect_and_stale_reconcile_connect_once() -> None:
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    manager = ConnectionManager(adb)
    config = registered()
    results = await asyncio.gather(*(manager.connect(config) for _ in range(5)))
    assert all(result.state == DeviceState.ONLINE for result in results)
    await manager.reconcile([config], {})
    assert adb.connection_calls == ["192.0.2.1:5555"]


@pytest.mark.asyncio
async def test_manual_disconnect_and_registry_intent_suppress_reconnect() -> None:
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    manager = ConnectionManager(adb)
    config = registered()
    await manager.connect(config)
    assert (await manager.disconnect(config)).state == DeviceState.DISCONNECTED
    result = (await manager.reconcile([replace(config, auto_connect=False)], {}))[config.id]
    assert result.state == DeviceState.DISCONNECTED
    assert adb.connection_calls == ["192.0.2.1:5555"]
    assert "pixel-stock" in adb.devices
    await manager.forget(config.id)
    assert adb.disconnection_calls == ["192.0.2.1:5555"]


@pytest.mark.asyncio
async def test_exact_mdns_identity_dynamic_port_and_never_pairing_port() -> None:
    adb = FakeAdbClient()
    config = registered(
        connection_type=ConnectionType.WIRELESS_ADB,
        host=None,
        port=None,
        mdns_service="device._adb-tls-connect._tcp",
    )
    manager = ConnectionManager(adb)
    unrelated = MdnsService(
        "other._adb-tls-connect._tcp", "_adb-tls-connect._tcp", "192.0.2.1", 4000
    )
    pairing = MdnsService(
        "device._adb-tls-pairing._tcp", "_adb-tls-pairing._tcp", "192.0.2.1", 4001
    )
    result = (await manager.reconcile([config], {}, [unrelated, pairing]))[config.id]
    assert result.state == DeviceState.PAIRING_REQUIRED
    assert adb.connection_calls == []
    first = MdnsService(config.mdns_service or "", "_adb-tls-connect._tcp", "192.0.2.1", 4002)
    adb.endpoints[first.address] = DeviceState.ONLINE
    assert (await manager.reconcile([config], {}, [first]))[config.id].state == DeviceState.ONLINE
    second = replace(first, port=4003)
    adb.endpoints[second.address] = DeviceState.ONLINE
    snapshot = await adb.list_devices()
    result = (await manager.reconcile([config], snapshot, [second]))[config.id]
    assert result.state == DeviceState.ONLINE
    assert result.serial == second.address
    assert adb.disconnection_calls == [first.address]
    assert adb.connection_calls == [first.address, second.address]


@pytest.mark.asyncio
async def test_unauthorized_no_rapid_retries_and_usb_never_connects() -> None:
    adb = FakeAdbClient()
    manager = ConnectionManager(adb)
    config = registered()
    for _ in range(5):
        result = (await manager.reconcile([config], {"192.0.2.1:5555": DeviceState.UNAUTHORIZED}))[
            config.id
        ]
        assert result.state == DeviceState.UNAUTHORIZED
    assert adb.connection_calls == []
    usb = registered(connection_type=ConnectionType.USB, host=None, port=None, serial="missing")
    assert (await manager.reconcile([usb], {}))[usb.id].state == DeviceState.OFFLINE
    assert adb.connection_calls == []


class SlowAdb(FakeAdbClient):
    async def connect(self, address: str) -> CommandResult:
        await asyncio.sleep(10)
        return CommandResult()


@pytest.mark.asyncio
async def test_connection_timeout_is_structured_and_safe() -> None:
    result = await ConnectionManager(SlowAdb(), connect_timeout=0.01).connect(registered())
    assert result.state == DeviceState.ERROR
    assert result.error_code == "connection_timeout"
    assert result.retry_in_seconds is not None


class MissingAdb(FakeAdbClient):
    async def list_devices(self) -> dict[str, DeviceState]:
        raise FileNotFoundError("secret/path")


@pytest.mark.asyncio
async def test_unavailable_does_not_expose_exception_details() -> None:
    result = await ConnectionManager(MissingAdb()).connect(registered())
    assert result.state == DeviceState.ADB_UNAVAILABLE
    assert "secret" not in (result.error_message or "")


@pytest.mark.asyncio
async def test_mdns_absence_keeps_manual_and_last_known_endpoint() -> None:
    adb = FakeAdbClient()
    config = registered(
        connection_type=ConnectionType.WIRELESS_ADB, mdns_service="device._adb-tls-connect._tcp"
    )
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    manager = ConnectionManager(adb)
    assert (await manager.connect(config)).state == DeviceState.ONLINE
    service = MdnsService(config.mdns_service or "", "_adb-tls-connect._tcp", "192.0.2.1", 4444)
    adb.endpoints[service.address] = DeviceState.ONLINE
    await manager.reconcile([config], await adb.list_devices(), [service])
    result = (await manager.reconcile([config], await adb.list_devices(), []))[config.id]
    assert result.state == DeviceState.ONLINE
    assert result.serial == service.address
    assert adb.disconnection_calls == ["192.0.2.1:5555"]
    unknown = registered(
        host=None,
        port=None,
        connection_type=ConnectionType.WIRELESS_ADB,
        mdns_service="unknown._adb-tls-connect._tcp",
    )
    assert (await ConnectionManager(adb).reconcile([unknown], {}, []))[
        unknown.id
    ].state == DeviceState.OFFLINE


@pytest.mark.asyncio
async def test_disabled_intent_does_not_mutate_changed_endpoint() -> None:
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    manager = ConnectionManager(adb)
    config = registered()
    await manager.connect(config)
    changed = replace(config, port=5556, auto_connect=False)
    await manager.reconcile([changed], {})
    assert adb.disconnection_calls == []
    assert adb.connection_calls == ["192.0.2.1:5555"]


class ReportedFailureAdb(FakeAdbClient):
    def __init__(self, output: str, exit_code: int) -> None:
        super().__init__()
        self.output = output
        self.exit_code = exit_code

    async def connect(self, address: str) -> CommandResult:
        return CommandResult(stdout=self.output, stderr="private-secret", exit_code=self.exit_code)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 1])
@pytest.mark.parametrize(
    ("output", "code"),
    [
        ("failed to connect: Connection refused", "connection_refused"),
        ("unable to connect: No route to host", "host_unreachable"),
        ("Network is unreachable", "host_unreachable"),
        ("failed to resolve host: Name or service not known", "host_resolution_failed"),
        ("nodename nor servname provided", "host_resolution_failed"),
        ("Connection timed out", "connection_timeout"),
        ("failed to authenticate to host", "pairing_required"),
        ("unknown failure private-secret", "connection_failed"),
    ],
)
async def test_safe_connection_failure_classification(
    output: str, code: str, exit_code: int
) -> None:
    result = await ConnectionManager(ReportedFailureAdb(output, exit_code)).connect(registered())
    assert result.error_code == code
    assert "private-secret" not in (result.error_message or "")
    assert result.state == (
        DeviceState.PAIRING_REQUIRED if code == "pairing_required" else DeviceState.OFFLINE
    )


@pytest.mark.asyncio
async def test_repeated_unauthorized_observation_does_not_inflate_retry_attempts() -> None:
    now = [0.0]
    adb = FakeAdbClient()
    manager = ConnectionManager(adb, clock=lambda: now[0], random_value=lambda: 1)
    config = registered()
    for _ in range(10):
        observed = await manager.reconcile([config], {"192.0.2.1:5555": DeviceState.UNAUTHORIZED})
        assert observed[config.id].retry_in_seconds == 60
    assert not adb.connection_calls
    now[0] = 60
    result = (await manager.reconcile([config], {}))[config.id]
    assert result.error_code == "connection_refused"
    assert result.retry_in_seconds == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("random_value", [-1.0, 0.0, 1.0, 2.0])
async def test_reconnect_jitter_stays_positive_and_bounded(random_value: float) -> None:
    now = [0.0]
    manager = ConnectionManager(
        FakeAdbClient(),
        backoff_initial=2,
        backoff_max=5,
        clock=lambda: now[0],
        random_value=lambda: random_value,
    )
    config = registered()
    for _ in range(10):
        result = (await manager.reconcile([config], {}))[config.id]
        assert result.retry_in_seconds is not None
        assert 0 < result.retry_in_seconds <= 5
        now[0] += result.retry_in_seconds
