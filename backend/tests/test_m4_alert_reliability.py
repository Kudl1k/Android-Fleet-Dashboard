"""Bounded history retention and prolonged/repeated connectivity incidents."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.alerts.engine import AlertEngine
from android_fleet.alerts.models import AlertState, Condition, RuleInput
from android_fleet.alerts.store import AlertStore
from android_fleet.devices.models import ConnectionType, Device, DeviceState
from android_fleet.devices.registry import SQLiteDeviceRegistry
from android_fleet.devices.service import FleetService
from android_fleet.metrics.history import MetricHistoryStore


async def test_prolonged_offline_repeated_reconnect_and_resolved_retention(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    await store.initialize()
    service = FleetService(
        FakeAdbClient(), SQLiteDeviceRegistry(":memory:"), MetricHistoryStore(":memory:")
    )
    service.devices["device"] = Device(
        "device", "serial", "Device", DeviceState.OFFLINE, ConnectionType.USB
    )
    now = datetime.now(UTC)
    service.devices["device"].last_seen = now - timedelta(days=1)
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(name="Offline", condition=Condition.OFFLINE, threshold=30, duration_seconds=0)
    )
    await engine.evaluate(now)
    for day in range(1, 5):
        await engine.evaluate(now + timedelta(days=day))
    assert (await store.events())[1] == 1
    assert (await store.active())[0].state == AlertState.FIRING
    assert await store.cleanup(60, now=now + timedelta(days=6)) == 0
    for cycle in range(3):
        timestamp = now + timedelta(days=6, minutes=cycle * 2)
        service.devices["device"].state = DeviceState.ONLINE
        await engine.evaluate(timestamp)
        assert await store.active() == []
        service.devices["device"].state = DeviceState.OFFLINE
        service.devices["device"].last_seen = timestamp
        await engine.evaluate(timestamp + timedelta(seconds=31))
        await engine.evaluate(timestamp + timedelta(seconds=32))
        assert len(await store.active()) == 1
    assert (await store.events())[1] == 4
    assert await store.cleanup(60, now=now + timedelta(days=7)) == 3
    await store.close()
    await store.initialize()
    assert (await store.events())[1] == 1
    assert (await store.active())[0].state == AlertState.FIRING
    await store.close()
