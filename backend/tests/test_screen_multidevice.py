"""Dual-device acceptance over real loopback sockets; no Android hardware involved."""

import asyncio
import json
import struct
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from android_fleet.adb.fake import FakeAdbClient, FakeAdbProcess
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.screen.bridge import ScrcpyBridge, VideoPacket, encode_input
from android_fleet.screen.manager import ScreenManager, Session
from android_fleet.screen.models import InputEvent, ScreenConfig, SessionState
from android_fleet.security import ROLE_PERMISSIONS, Actor, SecurityService

# Synthetic baseline SPS for 320x640; config uses official Annex B framing.
CONFIG = bytes.fromhex("000000016742001ff40a028fe8")


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        for _ in range(500):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("Timed out waiting for transport state")


class DeviceTransport:
    """Two sockets per capture, matching official scrcpy video/control ordering."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.server: asyncio.Server | None = None
        self.writers: list[asyncio.StreamWriter] = []
        self.videos: list[asyncio.StreamWriter] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.inputs: asyncio.Queue[bytes] = asyncio.Queue()
        self.connections = 0
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.connected, "127.0.0.1", 0)
        self.port = int(self.server.sockets[0].getsockname()[1])

    def connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        video = self.connections % 2 == 1
        self.writers.append(writer)
        task = asyncio.create_task(self.serve(reader, writer, video))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, video: bool
    ) -> None:
        try:
            if video:
                self.videos.append(writer)
                writer.write(b"\0" + struct.pack(">III", 0x68323634, 320, 640))
                writer.write(VideoPacket(CONFIG, 0, config=True).wire())
                writer.write(self.frame().wire())
                await writer.drain()
                await reader.read()
            else:
                while True:
                    # Test sends only complete navigation key-down/key-up pairs.
                    self.inputs.put_nowait(await reader.readexactly(28))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    def frame(self) -> VideoPacket:
        # Tagged synthetic IDR access units prove routing, without decoder claims.
        return VideoPacket(b"\0\0\0\1\x65" + self.name.encode(), 12345, keyframe=True)

    async def emit(self) -> None:
        self.videos[-1].write(self.frame().wire())
        await self.videos[-1].drain()

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in self.writers:
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


class TrackedProcess(FakeAdbProcess):
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class RoutedAdb(FakeAdbClient):
    def __init__(self, devices: dict[str, DeviceTransport]) -> None:
        super().__init__()
        self.transports = devices
        self.forwards: dict[tuple[str, int], str] = {}
        self.removed: list[tuple[str, int]] = []
        self.processes: list[TrackedProcess] = []

    async def start_shell(self, serial: str, argv: tuple[str, ...]) -> TrackedProcess:
        self.calls.append((serial, argv))
        process = TrackedProcess()
        self.processes.append(process)
        return process

    async def forward(self, serial: str, socket: str) -> int:
        port = self.transports[serial].port
        self.forwards[serial, port] = socket
        return port

    async def remove_forward(self, serial: str, port: int, *, socket: str | None = None) -> None:
        assert self.forwards[serial, port] == socket
        self.forwards.pop((serial, port))
        self.removed.append((serial, port))

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        assert serial in self.transports
        self.calls.append((serial, argv))
        return CommandResult(exit_code=0)


async def attach(manager: ScreenManager, device: str, owner: Actor) -> Session:
    session = await manager.create(device, owner, ScreenConfig())
    await until(lambda: session.state == SessionState.STREAMING)
    ticket = await manager.ticket(session, owner)
    await manager.attach(session.id, ticket["ticket"])
    await until(lambda: any(isinstance(item, bytes) for item in session.queue._queue))
    return session


async def test_real_tcp_multidevice_routing_reconnect_and_cleanup(tmp_path: Path) -> None:
    transports = {name: DeviceTransport(name) for name in ("phone", "tablet")}
    for transport in transports.values():
        await transport.start()
    settings = Settings(registry_path=tmp_path / "registry.sqlite")
    security = SecurityService(settings, tmp_path / "audit.sqlite")
    await security.initialize()
    adb = RoutedAdb(transports)
    manifest = tmp_path / "transports.json"
    bridge = ScrcpyBridge(adb, tmp_path / "server", state_path=manifest)
    fleet = SimpleNamespace(
        get=lambda name: SimpleNamespace(
            state=DeviceState.ONLINE, serial=name, capabilities={"adb_shell"}, sdk=36
        )
    )
    manager = ScreenManager(adb, fleet, security, settings, bridge=bridge)
    owners = {
        name: Actor(name, "operator", ROLE_PERMISSIONS["operator"], frozenset({name}))
        for name in transports
    }
    try:
        first = await attach(manager, "phone", owners["phone"])
        second = await attach(manager, "tablet", owners["tablet"])
        for session, name in ((first, "phone"), (second, "tablet")):
            await until(
                lambda name=name, session=session: (
                    transports[name].frame().wire() in list(session.queue._queue)
                )
            )
            assert transports[name].frame().wire() in list(session.queue._queue)
            opposite = "tablet" if name == "phone" else "phone"
            assert transports[opposite].frame().wire() not in list(session.queue._queue)
            await manager.acquire(session, owners[name])
        for session, name, key in ((first, "phone", "back"), (second, "tablet", "home")):
            await manager.input(session, owners[name], InputEvent(type="nav", key=key))
            async with asyncio.timeout(1):
                assert await transports[name].inputs.get() == encode_input(
                    {"type": "nav", "key": key}
                )
        with pytest.raises(HTTPException) as denied:
            await manager.input(first, owners["tablet"], InputEvent(type="nav", key="home"))
        assert denied.value.status_code == 403
        assert all(transport.inputs.empty() for transport in transports.values())
        second_stream = second.stream
        first_stream = first.stream
        # Only the first device's video channel loses its connection.
        transports["phone"].videos[-1].close()
        await until(lambda: first.state == SessionState.RECONNECTING)
        assert not first.control and second.control
        assert second.stream is second_stream and second.state == SessionState.STREAMING
        while not second.queue.empty():
            second.queue.get_nowait()
        await transports["tablet"].emit()
        await until(lambda: transports["tablet"].frame().wire() in list(second.queue._queue))
        await manager.input(second, owners["tablet"], InputEvent(type="nav", key="back"))
        async with asyncio.timeout(1):
            assert await transports["tablet"].inputs.get() == encode_input(
                {"type": "nav", "key": "back"}
            )
        await until(
            lambda: first.state == SessionState.STREAMING and first.stream is not first_stream
        )
        assert first.reconnect_attempts == 1 and not first.control
        assert second.reconnect_attempts == 0 and second.stream is second_stream
        assert transports["phone"].connections == 4
        assert transports["tablet"].connections == 2
        assert adb.removed == [("phone", transports["phone"].port)]
        assert len(adb.forwards) == 2
        assert manager.metrics()["active_viewers"] == 2
        await manager.stop(first, "browser_disconnected")
        assert second.state == SessionState.STREAMING and second.control
        await manager.close()
        assert not adb.forwards
        assert json.loads(manifest.read_text()) == {}
        assert len(adb.removed) == 3
        assert len(adb.processes) == 3 and all(process.closed for process in adb.processes)
        assert all(session.task is not None and session.task.done() for session in (first, second))
        assert manager.metrics()["active_sessions"] == 0
        assert manager.cleanup_failures == 0
        history = await security.history()
        assert any(item["error"] == "permission_denied" for item in history["items"])
    finally:
        await manager.close()
        for transport in transports.values():
            await transport.close()
