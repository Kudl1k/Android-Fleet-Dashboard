import asyncio
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.security import Actor
from android_fleet.terminal.manager import TerminalManager
from android_fleet.terminal.models import SessionState, TerminalConfig, TerminalMessage


class Security:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    async def authorize_device(self, actor: Actor, device_id: str, permission: str) -> None:
        if (
            permission not in actor.permissions
            or actor.device_ids is not None
            and device_id not in actor.device_ids
        ):
            raise HTTPException(403)

    async def audit(self, *args: Any, **kwargs: Any) -> None:
        self.events.append(args)


@pytest.fixture
async def manager(tmp_path: Path) -> Any:
    adb = FakeAdbClient()
    device = Device(
        "registered",
        "pixel-stock",
        "Stock",
        DeviceState.ONLINE,
        capabilities={DeviceCapability.ADB_SHELL},
    )
    fleet = SimpleNamespace(adb=adb, get=lambda _: device)
    settings = SimpleNamespace(
        terminal_path=tmp_path / "terminal.sqlite3",
        registry_path=tmp_path / "registry.sqlite3",
        terminal_adb_enabled=True,
        terminal_max_sessions=3,
        terminal_max_per_user=2,
        terminal_max_per_device=2,
        terminal_queue_chunks=16,
        terminal_idle_seconds=300,
        terminal_lifetime_seconds=3600,
        terminal_allowed_origins=("http://localhost:8088",),
    )
    instance = TerminalManager(settings, fleet, Security(), None)
    await instance.initialize()
    yield instance
    await instance.close()


ACTOR = Actor(
    "admin",
    "administrator",
    frozenset({"terminal:adb", "terminal:view", "terminal:session:terminate"}),
)
CONFIG = TerminalConfig(connection_type="adb", device_id="registered")


async def test_lifecycle_controls_resize_and_metadata(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    ticket = await manager.ticket(session, ACTOR)
    assert await manager.attach(session.id, ticket["ticket"]) is session
    assert (await session.queue.get())["data"].startswith("\x1b[32m")
    await manager.input(session, TerminalMessage(version=1, type="input", data="\x03"))
    assert (await session.queue.get())["data"] == "\x03"
    await manager.input(session, TerminalMessage(version=1, type="resize", cols=120, rows=40))
    assert session.transport.size == (120, 40)
    await manager.stop(session)
    assert session.state == SessionState.CLOSED
    assert session.transport.closed
    assert not session.task or session.task.done()
    history = await manager.history(ACTOR)
    assert history[0]["termination_reason"] == "user_closed"
    assert "data" not in history[0]


async def test_disabled_offline_scope_and_owner(manager: TerminalManager) -> None:
    manager.settings.terminal_adb_enabled = False
    with pytest.raises(HTTPException) as exc:
        await manager.create(ACTOR, CONFIG)
    assert exc.value.status_code == 403
    manager.settings.terminal_adb_enabled = True
    manager.service.adb.devices["pixel-stock"] = DeviceState.UNAUTHORIZED
    with pytest.raises(HTTPException):
        await manager.create(ACTOR, CONFIG)
    manager.service.adb.devices["pixel-stock"] = DeviceState.ONLINE
    session = await manager.create(ACTOR, CONFIG)
    with pytest.raises(HTTPException):
        await manager.get(session.id, Actor("other", "administrator", ACTOR.permissions))
    with pytest.raises(HTTPException):
        await manager.create(
            Actor("scoped", "administrator", ACTOR.permissions, frozenset()), CONFIG
        )


async def test_limits_single_use_and_close_invalidates_tickets(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    ticket = await manager.ticket(session, ACTOR)
    await manager.attach(session.id, ticket["ticket"])
    with pytest.raises(HTTPException):
        await manager.attach(session.id, ticket["ticket"])
    await manager.create(ACTOR, CONFIG)
    with pytest.raises(HTTPException) as exc:
        await manager.create(ACTOR, CONFIG)
    assert exc.value.status_code == 429
    await manager.stop(session)
    assert not manager.tickets


async def test_idle_lifetime_and_backend_recovery(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    session.last_activity = time.monotonic() - 400
    await asyncio.sleep(1.1)
    assert session.state == SessionState.TIMED_OUT
    second = await manager.create(ACTOR, CONFIG)
    second.created_at = time.time() - 4000
    await asyncio.sleep(1.1)
    assert second.termination_reason == "lifetime_timeout"
    third = await manager.create(ACTOR, CONFIG)
    await manager._save(third)
    replacement = TerminalManager(manager.settings, manager.service, manager.security, None)
    await replacement.initialize()
    try:
        record = next(r for r in await replacement.history(ACTOR) if r["id"] == third.id)
        assert record["termination_reason"] == "backend_restart"
        assert not replacement.sessions
    finally:
        await replacement.close()
    with sqlite3.connect(manager.path) as db:
        assert len(db.execute("SELECT * FROM terminal_sessions").fetchall()) == 3


async def test_rate_and_validation(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    session.rate_messages = 100
    with pytest.raises(HTTPException) as exc:
        await manager.input(session, TerminalMessage(version=1, type="heartbeat"))
    assert exc.value.status_code == 429
    for payload in (
        {"version": 2, "type": "close"},
        {"version": 1, "type": "resize", "cols": 0, "rows": 24},
        {"version": 1, "type": "input", "data": "x" * 4097},
        {"version": 1, "type": "heartbeat", "data": "secret"},
    ):
        with pytest.raises(ValueError):
            TerminalMessage.model_validate(payload)


async def test_slow_client_bounded_queue_and_transport_failure(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    await session.queue.get()
    assert session.transport is not None
    # The producer blocks at the configured queue bound, then fails cleanly.
    for _ in range(manager.settings.terminal_queue_chunks + 2):
        await session.transport.write(b"output")
    assert session.queue.qsize() <= manager.settings.terminal_queue_chunks
    await asyncio.sleep(5.1)
    assert session.state == SessionState.FAILED
    assert session.termination_reason == "transport_failed"
    assert session.transport.closed


async def test_device_disconnect_and_browser_disconnect_cleanup(manager: TerminalManager) -> None:
    session = await manager.create(ACTOR, CONFIG)
    manager.service.get("registered").state = DeviceState.OFFLINE
    await asyncio.sleep(1.1)
    assert session.termination_reason == "device_disconnected"
    assert session.transport.closed


async def test_ssh_session_lifecycle_and_profile_acl(manager: TerminalManager) -> None:
    from unittest.mock import AsyncMock

    from android_fleet.adb.fake import FakeTerminal

    transport = FakeTerminal()
    manager.ssh_gateway = SimpleNamespace(
        profiles=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(device_id=None))),
        authorize=AsyncMock(),
        open=AsyncMock(return_value=transport),
    )
    actor = Actor("ssh-user", "operator", frozenset({"terminal:ssh", "terminal:view"}))
    session = await manager.create(
        actor, TerminalConfig(connection_type="ssh", profile_id="approved")
    )
    assert session.state == "active"
    assert manager.metrics()["active_ssh"] == 1
    await manager.input(session, TerminalMessage(version=1, type="input", data="hello"))
    assert manager.ssh_gateway.authorize.await_count >= 2
    manager.ssh_gateway.authorize.side_effect = HTTPException(403)
    with pytest.raises(HTTPException):
        await manager.ticket(session, actor)
    await manager.stop(session)
    assert transport.closed
    assert manager.metrics()["active_ssh"] == 0
