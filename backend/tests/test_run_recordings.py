"""Run-isolated, authorized device histories and collector lifecycle."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from android_fleet.adb.fake import FakeAdbClient, FakeTerminal
from android_fleet.core.settings import Settings
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.metrics.models import MetricSnapshot, MetricValue
from android_fleet.security import Actor, SecurityService
from android_fleet.terminal.api import router
from android_fleet.terminal.manager import TerminalManager
from android_fleet.terminal.models import TerminalConfig


@pytest.fixture
async def runtime(tmp_path: Path) -> Any:
    settings = Settings(control_token="recording-token", registry_path=tmp_path / "devices.db")
    security = SecurityService(settings, tmp_path / "audit.db")
    await security.initialize()
    device = Device(
        "phone",
        "pixel-rooted",
        "Phone",
        DeviceState.ONLINE,
        capabilities={DeviceCapability.ADB_SHELL},
    )

    async def sample(_: str) -> MetricSnapshot:
        return MetricSnapshot(
            "phone",
            datetime.now(UTC),
            (
                MetricValue("cpu_usage", 0.5, "ratio"),
                MetricValue("cpu_core_usage", 0.8, "ratio", (("core", "0"),)),
                MetricValue("memory_used", 1024, "bytes"),
            ),
        )

    fleet = SimpleNamespace(
        adb=FakeAdbClient(), get=lambda _: device, sample_device=AsyncMock(side_effect=sample)
    )
    gateway = SimpleNamespace(
        authorize=AsyncMock(),
        profiles=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(device_id="phone"))),
        open=AsyncMock(side_effect=lambda *args: FakeTerminal()),
    )
    manager = TerminalManager(settings, fleet, security, gateway)
    await manager.initialize()
    actor = security._credentials[0][1]
    app = FastAPI()
    app.include_router(router(manager, security))
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://test",
        headers={"Authorization": "Bearer recording-token"},
    ) as client:
        yield manager, actor, fleet, gateway, client
    await manager.close()
    await security.close()


def config() -> TerminalConfig:
    return TerminalConfig(
        connection_type="ssh", profile_id="approved", command="benchmark", record_device=True
    )


async def test_samples_isolated_saved_paginated_and_survive_restart(runtime: Any) -> None:
    manager, actor, fleet, gateway, client = runtime
    session = await manager.create(actor, config())
    # Stop the periodic worker deterministically, then take a second real sample.
    session.recording_task.cancel()
    await asyncio.gather(session.recording_task, return_exceptions=True)
    await manager._record_sample(session)
    await manager.stop(session)
    assert session.sample_count >= 2
    assert session.recording_task.done()
    assert session.available_metrics == {"cpu_usage", "cpu_core_usage", "memory_used"}
    before = fleet.sample_device.await_count
    response = await client.get(
        f"/api/v1/terminal/sessions/{session.id}/telemetry", params={"limit": 1}
    )
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["device_id"] == "phone"
    assert len(first["points"]) == 1
    assert first["next_cursor"]
    second = await client.get(
        f"/api/v1/terminal/sessions/{session.id}/telemetry",
        params={
            "limit": 1,
            "cursor": first["next_cursor"],
            "end": first["end"],
        },
    )
    assert second.status_code == 200
    assert second.json()["points"] != first["points"]
    assert fleet.sample_device.await_count == before  # Read API never performs ADB I/O.
    manager.sessions.pop(session.id)
    restored = await manager.recording_metadata(session.id, actor)
    assert restored["device_recording"]["sample_count"] == session.sample_count
    assert (await client.get(f"/api/v1/terminal/sessions/{session.id}/telemetry")).json()["points"]
    other = Actor("other", "administrator", actor.permissions)
    with pytest.raises(HTTPException) as denial:
        await manager.recording_metadata(session.id, other)
    assert denial.value.status_code == 404
    assert (
        await client.get(
            f"/api/v1/terminal/sessions/{session.id}/telemetry",
            headers={"Authorization": "Bearer wrong"},
        )
    ).status_code == 401


async def test_offline_and_denied_observations_never_fabricate_samples(runtime: Any) -> None:
    manager, actor, fleet, _, _ = runtime
    session = await manager.create(actor, config())
    session.recording_task.cancel()
    await asyncio.gather(session.recording_task, return_exceptions=True)
    before = session.sample_count
    fleet.sample_device.side_effect = None
    fleet.sample_device.return_value = None
    await manager._record_sample(session)
    assert session.sample_count == before
    assert "gap" in session.recording_error
    fleet.sample_device.side_effect = TimeoutError
    await manager._record_sample(session)
    assert session.sample_count == before
    assert "gap" in session.recording_error
    manager.ssh_gateway.authorize.side_effect = HTTPException(403)
    await manager._record_sample(session)
    assert "authorization" in session.recording_error
    await manager.stop(session)


async def test_recording_requires_linked_online_authorized_device(runtime: Any) -> None:
    manager, actor, fleet, gateway, _ = runtime
    gateway.profiles.get.return_value.device_id = None
    with pytest.raises(HTTPException) as denial:
        await manager.create(actor, config())
    assert denial.value.status_code == 409
    gateway.profiles.get.return_value.device_id = "phone"
    fleet.get("phone").state = DeviceState.OFFLINE
    with pytest.raises(HTTPException):
        await manager.create(actor, config())
    fleet.get("phone").state = DeviceState.ONLINE
    limited = Actor("limited", "operator", frozenset({"terminal:ssh", "terminal:view"}))
    with pytest.raises(HTTPException) as denial:
        await manager.create(limited, config())
    assert denial.value.status_code == 403
    assert not manager.sessions


async def test_no_telemetry_for_runs_without_opt_in_and_bad_queries(runtime: Any) -> None:
    manager, actor, _, _, client = runtime
    session = await manager.create(
        actor, TerminalConfig(connection_type="ssh", profile_id="approved", command="benchmark")
    )
    assert (
        await client.get(f"/api/v1/terminal/sessions/{session.id}/telemetry")
    ).status_code == 409
    await manager.stop(session)
    recorded = await manager.create(actor, config())
    await manager.stop(recorded)
    for params in (
        {"end": "2020-01-01T00:00:00"},
        {"metric": "invented"},
        {"limit": 0},
        {"cursor": "invalid"},
    ):
        response = await client.get(
            f"/api/v1/terminal/sessions/{recorded.id}/telemetry", params=params
        )
        assert response.status_code == 422
    start = datetime.fromtimestamp(recorded.created_at, UTC)
    other = await manager.create(actor, config())
    await manager.stop(other)
    page = await manager.recordings.query(
        recorded.id, start=start, end=datetime.now(UTC) + timedelta(seconds=1)
    )
    assert all(point.metric.name in recorded.available_metrics for point in page.points)
    assert len(page.points) == recorded.sample_count * 3


async def test_remote_completion_captures_final_sample_and_drains_worker(runtime: Any) -> None:
    manager, actor, _, _, client = runtime
    session = await manager.create(actor, config())
    await session.transport.write(b"")
    await asyncio.wait_for(session.task, timeout=2)
    assert session.state == "closed"
    assert session.sample_count >= 2
    assert session.recording_task.done()
    assert session.last_sample_at.timestamp() <= session.ended_at
    response = await client.get(f"/api/v1/terminal/sessions/{session.id}/telemetry")
    assert response.status_code == 200
    count = len(response.json()["points"])
    await manager.recordings.close()
    await manager.recordings.initialize()
    manager.sessions.pop(session.id)
    assert (
        len(
            (await client.get(f"/api/v1/terminal/sessions/{session.id}/telemetry")).json()["points"]
        )
        == count
    )
    scoped = Actor(actor.identity, actor.role, actor.permissions, frozenset())
    with pytest.raises(HTTPException) as denied:
        await manager.recording_metadata(session.id, scoped)
    assert denied.value.status_code == 403
