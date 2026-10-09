"""Alert persistence, lifecycle, unknown observations and API authorization."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.alerts.engine import AlertEngine
from android_fleet.alerts.models import AlertState, Condition, Rule, RuleInput
from android_fleet.alerts.store import AlertError, AlertStore
from android_fleet.core.settings import Settings
from android_fleet.devices.models import ConnectionType, Device, DeviceState
from android_fleet.devices.registry import SQLiteDeviceRegistry
from android_fleet.devices.service import FleetService
from android_fleet.main import create_app
from android_fleet.metrics.history import MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def fleet() -> FleetService:
    service = FleetService(
        FakeAdbClient(), SQLiteDeviceRegistry(":memory:"), MetricHistoryStore(":memory:")
    )
    service.devices["test"] = Device(
        "test", "serial", "Test", DeviceState.ONLINE, ConnectionType.USB
    )
    return service


def sample(service: FleetService, now: datetime, level: float | None) -> None:
    values = () if level is None else (MetricValue("battery_level", level, "ratio"),)
    service.snapshots["test"] = MetricSnapshot("test", now, values)


async def test_duration_hysteresis_dedup_ack_resolution_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "alerts.sqlite3"
    store = AlertStore(path)
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(
            name="Low battery",
            condition=Condition.BATTERY_LOW,
            threshold=0.2,
            hysteresis=0.05,
            duration_seconds=10,
        )
    )
    now = datetime.now(UTC)
    sample(service, now, 0.1)
    await engine.evaluate(now)
    events, count = await store.events()
    assert count == 1 and events[0].state == AlertState.PENDING
    await engine.evaluate(now + timedelta(seconds=11))
    events, count = await store.events()
    assert count == 1 and events[0].state == AlertState.FIRING
    event = await engine.acknowledge(events[0].id)
    assert event.state == AlertState.ACKNOWLEDGED
    await store.close()
    await store.initialize()
    sample(service, now, 0.22)
    await engine.evaluate(now + timedelta(seconds=12))
    assert (await store.event(event.id)).state == AlertState.ACKNOWLEDGED
    sample(service, now, 0.3)
    await engine.evaluate(now + timedelta(seconds=13))
    assert (await store.event(event.id)).state == AlertState.RESOLVED
    sample(service, now, 0.1)
    await engine.evaluate(now + timedelta(seconds=14))
    assert (await store.events())[1] == 2
    await store.close()


async def test_missing_unsupported_stale_offline_and_override() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=10)
    global_rule = Rule(
        id="global",
        name="Battery",
        condition=Condition.BATTERY_LOW,
        threshold=0.2,
        duration_seconds=0,
    )
    await store.save_rule(global_rule)
    now = datetime.now(UTC)
    sample(service, now, None)
    await engine.evaluate(now)
    assert (await store.events())[1] == 0
    sample(service, now - timedelta(seconds=11), 0.1)
    await engine.evaluate(now)
    assert (await store.events())[1] == 0
    sample(service, now, 0.1)
    service.devices["test"].state = DeviceState.OFFLINE
    await engine.evaluate(now)
    assert (await store.events())[1] == 0
    service.devices["test"].state = DeviceState.ONLINE
    await store.save_rule(
        Rule(
            id="override",
            **global_rule.model_dump(exclude={"id", "device_id", "enabled"}),
            device_id="test",
            enabled=False,
        )
    )
    await engine.evaluate(now)
    assert (await store.events())[1] == 0
    await store.close()


async def test_offline_reconnect_and_telemetry_missing() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    now = datetime.now(UTC)
    service.devices["test"].state = DeviceState.OFFLINE
    service.devices["test"].last_seen = now - timedelta(seconds=100)
    await engine.save_rule(
        RuleInput(name="Offline", condition=Condition.OFFLINE, threshold=30, duration_seconds=0)
    )
    await engine.evaluate(now)
    events, _ = await store.events()
    assert events[0].state == AlertState.FIRING
    service.devices["test"].state = DeviceState.ONLINE
    await engine.evaluate(now)
    assert (await store.event(events[0].id)).state == AlertState.RESOLVED
    await engine.save_rule(
        RuleInput(
            name="Stale", condition=Condition.TELEMETRY_STALE, threshold=30, duration_seconds=0
        )
    )
    await engine.evaluate(now)
    assert await store.active() == []
    await engine.evaluate(now + timedelta(seconds=31))
    assert len(await store.active()) == 1
    sample(service, now + timedelta(seconds=32), 0.5)
    await engine.evaluate(now + timedelta(seconds=32))
    assert await store.active() == []
    await store.close()


def test_api_auth_crud_validation_and_pagination() -> None:
    app = create_app(
        settings=Settings(
            anonymous_viewer=True,
            control_token="test-secret",
            registry_path=":memory:",
            history_path=":memory:",
            seed_fake_devices=False,
        )
    )
    with TestClient(app) as client:
        rules = client.get("/api/v1/alerts/rules").json()
        assert len(rules) == 8
        body = {
            "name": "Device CPU",
            "condition": "cpu_high",
            "threshold": 0.9,
            "device_id": "test",
        }
        assert client.post("/api/v1/alerts/rules", json=body).status_code == 403
        headers = {"Authorization": "Bearer test-secret"}
        response = client.post("/api/v1/alerts/rules", json=body, headers=headers)
        assert response.status_code == 201
        identifier = response.json()["id"]
        assert (
            client.patch(
                f"/api/v1/alerts/rules/{identifier}", json={"enabled": False}, headers=headers
            ).json()["enabled"]
            is False
        )
        assert (
            client.patch(
                f"/api/v1/alerts/rules/{identifier}", json={"threshold": 2}, headers=headers
            ).status_code
            == 422
        )
        assert client.get("/api/v1/alerts?limit=10&offset=5").json() == {
            "items": [],
            "total": 0,
            "limit": 10,
            "offset": 5,
        }
        assert client.post("/api/v1/alerts/missing/acknowledge", headers=headers).status_code == 404
        assert (
            client.delete(f"/api/v1/alerts/rules/{identifier}", headers=headers).status_code == 204
        )
        assert (
            client.delete(f"/api/v1/alerts/rules/{identifier}", headers=headers).status_code == 404
        )


async def test_reject_newer_schema(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "newer.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=2")
    connection.close()
    with pytest.raises(AlertError, match="newer"):
        await AlertStore(path).initialize()


@pytest.mark.parametrize(
    ("condition", "metrics", "threshold"),
    [
        (Condition.CPU_HIGH, (MetricValue("cpu_usage", 0.95, "ratio"),), 0.9),
        (
            Condition.MEMORY_HIGH,
            (MetricValue("memory_total", 100, "bytes"), MetricValue("memory_used", 95, "bytes")),
            0.9,
        ),
        (
            Condition.STORAGE_LOW,
            (
                MetricValue("storage_total", 100, "bytes", (("mount", "/data"),)),
                MetricValue("storage_free", 5, "bytes", (("mount", "/data"),)),
            ),
            0.1,
        ),
        (Condition.BATTERY_TEMPERATURE, (MetricValue("battery_temperature", 50, "celsius"),), 45),
        (
            Condition.DEVICE_TEMPERATURE,
            (
                MetricValue(
                    "thermal_temperature", 80, "celsius", (("sensor", "cpu"), ("type", "cpu"))
                ),
            ),
            70,
        ),
    ],
)
async def test_supported_condition_evaluation(
    condition: Condition, metrics: tuple[MetricValue, ...], threshold: float
) -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(name="Threshold", condition=condition, threshold=threshold, duration_seconds=0)
    )
    now = datetime.now(UTC)
    service.snapshots["test"] = MetricSnapshot("test", now, metrics)
    await engine.evaluate(now)
    assert (await store.active())[0].state == AlertState.FIRING
    service.snapshots["test"] = MetricSnapshot("test", now, ())
    await engine.evaluate(now)
    assert (await store.active())[0].state == AlertState.FIRING
    await store.close()


async def test_defaults_not_recreated_after_deletion_and_disabled_resolution(
    tmp_path: Path,
) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.initialize()
    for rule in await store.rules():
        await store.delete_rule(rule.id)
    await store.close()
    await engine.initialize()
    assert await store.rules() == []
    rule = await engine.save_rule(
        RuleInput(
            name="Battery", condition=Condition.BATTERY_LOW, threshold=0.2, duration_seconds=0
        )
    )
    now = datetime.now(UTC)
    sample(service, now, 0.1)
    await engine.evaluate(now)
    await engine.save_rule(
        RuleInput(**rule.model_dump(exclude={"id", "enabled"}), enabled=False), rule.id
    )
    assert await store.active() == []
    await store.close()


@pytest.mark.parametrize(
    ("condition", "threshold", "hysteresis"),
    [
        (Condition.CPU_HIGH, 0.1, 0.2),
        (Condition.BATTERY_LOW, 0.9, 0.2),
        (Condition.OFFLINE, 0, 1),
    ],
)
def test_unreachable_hysteresis_recovery_rejected(
    condition: Condition, threshold: float, hysteresis: float
) -> None:
    with pytest.raises(ValueError):
        RuleInput(
            name="Invalid recovery", condition=condition, threshold=threshold, hysteresis=hysteresis
        )


async def test_device_removed_mid_evaluation_and_invalid_metric() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    rule = RuleInput(
        name="Battery", condition=Condition.BATTERY_LOW, threshold=0.2, duration_seconds=0
    )
    await engine.save_rule(rule)
    now = datetime.now(UTC)
    sample(service, now, float("nan"))
    await engine.evaluate(now)
    assert await store.active() == []
    sample(service, now, 0.1)
    await engine.evaluate(now)
    service.devices.clear()
    assert engine._value(Rule(id="test", **rule.model_dump()), "test", now) is None
    await engine.evaluate(now)
    assert await store.active() == []
    await store.close()


async def test_worker_recovers_from_persistence_outage() -> None:
    import asyncio

    store = AlertStore(":memory:")
    engine = AlertEngine(store, fleet(), max_age_seconds=90)
    worker = asyncio.create_task(engine.run(0.01))
    await asyncio.sleep(0.025)
    assert not engine.healthy
    await store.initialize()
    await asyncio.sleep(0.025)
    assert engine.healthy
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    await store.close()


async def test_fast_reconnect_resets_sustained_pending_observation() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(
            name="Battery", condition=Condition.BATTERY_LOW, threshold=0.2, duration_seconds=10
        )
    )
    now = datetime.now(UTC)
    sample(service, now, 0.1)
    await engine.evaluate(now)
    # Simulate the epoch change performed by disconnect/reconnect between alert ticks.
    service._generation["test"] = service.observation_generation("test") + 1
    sample(service, now + timedelta(seconds=11), 0.1)
    await engine.evaluate(now + timedelta(seconds=11))
    active = await store.active()
    assert len(active) == 1 and active[0].state == AlertState.PENDING
    assert active[0].started_at == now + timedelta(seconds=11)
    await engine.evaluate(now + timedelta(seconds=22))
    assert (await store.active())[0].state == AlertState.FIRING
    service._generation["test"] += 1
    await engine.evaluate(now + timedelta(seconds=23))
    assert (await store.active())[0].state == AlertState.FIRING
    await store.close()


async def test_process_restart_resets_pending_metric_duration(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.initialize()
    for rule in await store.rules():
        await store.delete_rule(rule.id)
    await engine.save_rule(
        RuleInput(
            name="Battery", condition=Condition.BATTERY_LOW, threshold=0.2, duration_seconds=10
        )
    )
    now = datetime.now(UTC)
    sample(service, now, 0.1)
    await engine.evaluate(now)
    await store.close()
    resumed = AlertEngine(store, service, max_age_seconds=90)
    await resumed.initialize()
    sample(service, now + timedelta(seconds=20), 0.1)
    await resumed.evaluate(now + timedelta(seconds=20))
    assert (await store.active())[0].state == AlertState.PENDING
    assert (await store.active())[0].started_at == now + timedelta(seconds=20)
    await store.close()


@pytest.mark.parametrize(
    "metric",
    [
        MetricValue(
            "thermal_temperature", float("inf"), "celsius", (("sensor", "cpu"), ("type", "cpu"))
        ),
        MetricValue("thermal_temperature", 1000, "celsius", (("sensor", "cpu"), ("type", "cpu"))),
        MetricValue("thermal_temperature", 80, "kelvin", (("sensor", "cpu"), ("type", "cpu"))),
        MetricValue("thermal_temperature", 80, "celsius"),
    ],
)
async def test_invalid_thermal_observation_is_unknown_and_stale(metric: MetricValue) -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(
            name="Heat", condition=Condition.DEVICE_TEMPERATURE, threshold=70, duration_seconds=0
        )
    )
    await engine.save_rule(
        RuleInput(
            name="Telemetry", condition=Condition.TELEMETRY_STALE, threshold=10, duration_seconds=0
        )
    )
    now = datetime.now(UTC)
    service.snapshots["test"] = MetricSnapshot("test", now, (metric,))
    await engine.evaluate(now)
    assert await store.active() == []
    # Fresh timestamps containing only invalid values must not hide missing telemetry.
    service.snapshots["test"] = MetricSnapshot("test", now + timedelta(seconds=11), (metric,))
    await engine.evaluate(now + timedelta(seconds=11))
    active = await store.active()
    assert len(active) == 1 and active[0].condition == Condition.TELEMETRY_STALE
    await store.close()


async def test_unknown_observation_breaks_pending_duration() -> None:
    store = AlertStore(":memory:")
    await store.initialize()
    service = fleet()
    engine = AlertEngine(store, service, max_age_seconds=90)
    await engine.save_rule(
        RuleInput(
            name="Battery", condition=Condition.BATTERY_LOW, threshold=0.2, duration_seconds=10
        )
    )
    now = datetime.now(UTC)
    sample(service, now, 0.1)
    await engine.evaluate(now)
    sample(service, now + timedelta(seconds=5), None)
    await engine.evaluate(now + timedelta(seconds=5))
    assert await store.active() == []
    sample(service, now + timedelta(seconds=11), 0.1)
    await engine.evaluate(now + timedelta(seconds=11))
    assert (await store.active())[0].state == AlertState.PENDING
    await engine.evaluate(now + timedelta(seconds=22))
    assert (await store.active())[0].state == AlertState.FIRING
    assert (await store.events())[1] == 2
    await store.close()


def test_all_alert_mutations_require_authorization() -> None:
    app = create_app(
        settings=Settings(
            anonymous_viewer=True,
            control_token="secret",
            registry_path=":memory:",
            history_path=":memory:",
            seed_fake_devices=False,
        )
    )
    with TestClient(app) as client:
        identifier = client.get("/api/v1/alerts/rules").json()[0]["id"]
        assert (
            client.patch(f"/api/v1/alerts/rules/{identifier}", json={"enabled": False}).status_code
            == 403
        )
        assert client.delete(f"/api/v1/alerts/rules/{identifier}").status_code == 403
        assert client.post("/api/v1/alerts/missing/acknowledge").status_code == 403
        assert client.get("/api/v1/alerts/rules").json()[0]["enabled"] is True
