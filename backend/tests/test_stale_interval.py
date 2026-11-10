"""Telemetry freshness follows each device's collection interval."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.alerts.engine import AlertEngine
from android_fleet.alerts.models import Condition, RuleInput
from android_fleet.alerts.store import AlertStore
from android_fleet.core.settings import Settings
from android_fleet.devices.models import ConnectionType, Device, DeviceState
from android_fleet.devices.registry import SQLiteDeviceRegistry
from android_fleet.devices.service import FleetService
from android_fleet.main import create_app
from android_fleet.metrics.exporter import render_metrics
from android_fleet.metrics.history import MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot, MetricValue

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
SLOW, FAST = "slow", "fast"
INTERVALS = {SLOW: 300.0, FAST: 30.0}


def fleet() -> FleetService:
    service = FleetService(
        FakeAdbClient(), SQLiteDeviceRegistry(":memory:"), MetricHistoryStore(":memory:")
    )
    for device_id in INTERVALS:
        service.devices[device_id] = Device(
            device_id, device_id, device_id, DeviceState.ONLINE, ConnectionType.USB
        )
        service.snapshots[device_id] = MetricSnapshot(
            device_id,
            NOW - timedelta(seconds=200),
            (MetricValue("battery_level", 0.5, "ratio"),),
        )
    service.metrics_interval_for = INTERVALS.__getitem__
    return service


def test_limit_grows_with_the_collection_interval() -> None:
    service = fleet()
    assert service.metrics_max_age(SLOW, 90) == 900
    assert service.metrics_max_age(FAST, 90) == 90  # unchanged at the default cadence
    service.metrics_interval_for = lambda _id: 10
    assert service.metrics_max_age(FAST, 90) == 90
    service.metrics_interval_for = None
    assert service.metrics_max_age(SLOW, 90) == 90


def test_exporter_keeps_slow_devices_between_samples() -> None:
    service = fleet()
    text = render_metrics(
        list(service.devices.values()),
        service.snapshots,
        max_age_seconds=90,
        max_age_for=lambda device_id: service.metrics_max_age(device_id, 90),
        now=NOW,
    ).decode()
    assert 'android_battery_level_ratio{device_id="slow"}' in text
    assert 'android_battery_level_ratio{device_id="fast"}' not in text


async def test_alerts_use_the_device_limit() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(
        store,
        service,
        max_age_seconds=90,
        max_age_for=lambda device_id: service.metrics_max_age(device_id, 90),
    )
    await engine.save_rule(
        RuleInput(
            name="Low battery",
            condition=Condition.BATTERY_LOW,
            threshold=0.6,
            hysteresis=0.01,
            duration_seconds=0,
        )
    )
    await engine.save_rule(
        RuleInput(
            name="Stale", condition=Condition.TELEMETRY_STALE, threshold=120, duration_seconds=0
        )
    )
    await engine.evaluate(NOW)
    events, _ = await store.events()
    fired = {(event.device_id, event.condition) for event in events}
    # The slow device's 200 s old sample is still current: it alerts on battery, not staleness.
    assert (SLOW, Condition.BATTERY_LOW) in fired
    assert (SLOW, Condition.TELEMETRY_STALE) not in fired
    # The fast device missed several samples.
    assert (FAST, Condition.TELEMETRY_STALE) in fired
    assert (FAST, Condition.BATTERY_LOW) not in fired
    await store.close()


async def test_current_metrics_respect_a_device_override() -> None:
    app = create_app(FakeAdbClient(), Settings(anonymous_viewer=True, control_token="admin"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            admin = {"Authorization": "Bearer admin"}
            response = await client.put(
                "/api/v1/settings/devices/pixel-rooted",
                json={"values": {"metrics_interval_seconds": 300}},
                headers=admin,
            )
            assert response.status_code == 200, response.text
            fleet = app.state.fleet
            for device_id in ("pixel-rooted", "pixel-stock"):
                snapshot = fleet.snapshots[device_id]
                fleet.snapshots[device_id] = replace(
                    snapshot, observed_at=datetime.now(UTC) - timedelta(seconds=200)
                )
            slow = (await client.get("/api/v1/devices/pixel-rooted/metrics")).json()
            default = (await client.get("/api/v1/devices/pixel-stock/metrics")).json()
            assert slow["stale"] is False and slow["values"]
            assert default["stale"] is True and default["values"] == []
