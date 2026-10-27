"""Operator-editable intervals: validation, persistence, API and per-device scheduling."""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.runtime_settings import InvalidSetting, RuntimeSettings
from android_fleet.core.settings import Settings
from android_fleet.main import create_app

ADMIN = {"Authorization": "Bearer settings-admin"}
DEFAULTS = {
    "metrics_interval_seconds": 30.0,
    "poll_interval_seconds": 30.0,
    "alerts_interval_seconds": 5.0,
}


async def test_values_validate_persist_and_restore_defaults(tmp_path: Path) -> None:
    store = RuntimeSettings(DEFAULTS, tmp_path / "settings.sqlite3")
    await store.initialize()
    await store.update({"metrics_interval_seconds": 10}, "jirka")
    await store.update_device("phone", {"metrics_interval_seconds": 5}, "jirka")
    assert store.device_value("phone", "metrics_interval_seconds") == 5
    assert store.device_value("other", "metrics_interval_seconds") == 10

    reloaded = RuntimeSettings(DEFAULTS, tmp_path / "settings.sqlite3")
    await reloaded.initialize()
    assert reloaded.value("metrics_interval_seconds") == 10
    assert reloaded.device_overrides() == {"phone": {"metrics_interval_seconds": 5}}

    await reloaded.update({"metrics_interval_seconds": None}, "jirka")
    assert reloaded.value("metrics_interval_seconds") == 30
    for bad in (
        {"metrics_interval_seconds": 1},
        {"metrics_interval_seconds": float("nan")},
        {"metrics_interval_seconds": True},
        {"control_token": 5},
    ):
        with pytest.raises(InvalidSetting):
            await reloaded.update(bad, "jirka")  # type: ignore[arg-type]
    with pytest.raises(InvalidSetting):
        await reloaded.update_device("phone", {"poll_interval_seconds": 10}, "jirka")


async def test_settings_api_requires_manage_and_audits(tmp_path: Path) -> None:
    app = create_app(
        FakeAdbClient(),
        Settings(
            registry_path=tmp_path / "devices.sqlite3",
            history_path=tmp_path / "history.sqlite3",
            seed_fake_devices=True,
            control_token=SecretStr("settings-admin"),
        ),
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app)
        async with AsyncClient(transport=transport, base_url="http://test") as anonymous:
            assert (await anonymous.get("/api/v1/settings")).status_code in (401, 403)
            denied = await anonymous.put(
                "/api/v1/settings", json={"values": {"metrics_interval_seconds": 10}}
            )
            assert denied.status_code in (401, 403)
        async with AsyncClient(transport=transport, base_url="http://test", headers=ADMIN) as c:
            listed = (await c.get("/api/v1/settings")).json()
            keys = {item["key"] for item in listed["settings"]}
            assert keys == set(DEFAULTS)
            changed = await c.put(
                "/api/v1/settings", json={"values": {"metrics_interval_seconds": 12}}
            )
            assert changed.status_code == 200
            assert app.state.runtime_settings.value("metrics_interval_seconds") == 12
            invalid = await c.put(
                "/api/v1/settings", json={"values": {"metrics_interval_seconds": 0.5}}
            )
            assert invalid.status_code == 422
            device_id = next(iter(app.state.fleet.devices))
            per_device = await c.put(
                f"/api/v1/settings/devices/{device_id}",
                json={"values": {"metrics_interval_seconds": 6}},
            )
            assert per_device.json()["devices"] == {device_id: {"metrics_interval_seconds": 6}}
            missing = await c.put(
                "/api/v1/settings/devices/nope", json={"values": {"metrics_interval_seconds": 6}}
            )
            assert missing.status_code == 404
            audit = (await c.get("/api/v1/audit?action=settings.update")).json()
            assert audit["total"] >= 1


async def test_metrics_loop_honours_per_device_intervals(tmp_path: Path) -> None:
    app = create_app(
        FakeAdbClient(),
        Settings(
            registry_path=tmp_path / "devices.sqlite3",
            history_path=tmp_path / "history.sqlite3",
            seed_fake_devices=True,
        ),
    )
    async with app.router.lifespan_context(app):
        fleet = app.state.fleet
        online = [d.id for d in fleet.devices.values() if d.state.value == "online"]
        assert len(online) >= 2
        fast, slow = online[0], online[1]
        calls: list[set[str]] = []

        async def record(only: set[str] | None = None) -> None:
            calls.append(set(only or ()))

        fleet.collect_metrics = record  # type: ignore[method-assign]
        fleet.metrics_interval_for = lambda device_id: 0.1 if device_id == fast else 100.0
        task = asyncio.create_task(fleet.run_metrics(100.0))
        await asyncio.sleep(0.45)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        collected = [device for batch in calls for device in batch]
        assert collected.count(fast) >= 3
        assert slow not in collected
