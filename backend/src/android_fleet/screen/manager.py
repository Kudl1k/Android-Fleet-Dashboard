"""Bounded, application-owned screen sessions; no durable control ownership."""

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from android_fleet.devices.models import DeviceCapability, DeviceState
from android_fleet.screen.models import InputEvent, ScreenConfig, SessionState
from android_fleet.security import Actor

ACTIVE = {SessionState.STARTING, SessionState.STREAMING, SessionState.RECONNECTING}
RESERVED = ACTIVE | {SessionState.STOPPING}


@dataclass
class Session:
    id: str
    device_id: str
    owner: Actor
    config: ScreenConfig
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    state: SessionState = SessionState.STARTING
    termination_reason: str | None = None
    control: bool = False
    stream: Any = None
    task: asyncio.Task[None] | None = None
    queue: asyncio.Queue[bytes | dict[str, Any]] = field(default_factory=asyncio.Queue)
    attached: bool = False
    dropping: bool = False
    codec_packet: bytes | None = None
    bytes_transferred: int = 0
    dropped_frames: int = 0
    startup_seconds: float | None = None
    rate_started: float = 0
    rate_count: int = 0
    reconnect_attempts: int = 0
    input_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    held_keys: set[int] = field(default_factory=set)
    pointer: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "owner": self.owner.identity,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "state": self.state,
            "requested_capabilities": ["screen:view"],
            "config": self.config.model_dump(),
            "control": self.control,
            "termination_reason": self.termination_reason,
            "width": getattr(self.stream, "width", None),
            "height": getattr(self.stream, "height", None),
            "statistics": {
                "bytes_transferred": self.bytes_transferred,
                "dropped_frames": self.dropped_frames,
                "startup_seconds": self.startup_seconds,
            },
        }


class ScreenManager:
    def __init__(
        self, adb: Any, fleet: Any, security: Any, settings: Any, *, bridge: Any = None
    ) -> None:
        if bridge is None:
            from android_fleet.screen.bridge import ScrcpyBridge

            bridge = ScrcpyBridge(
                adb,
                settings.screen_server_path,
                state_path=(
                    Path(settings.registry_path).parent / "screen-transports.json"
                    if str(settings.registry_path) != ":memory:"
                    else None
                ),
            )
        self.bridge = bridge
        self.fleet = fleet
        self.security = security
        self.settings = settings
        self.sessions: dict[str, Session] = {}
        self.tickets: dict[str, tuple[str, Actor, float]] = {}
        self.lock = asyncio.Lock()
        self.reaper: asyncio.Task[None] | None = None
        self.failures = 0
        self.cleanup_failures = 0
        self.total_bytes = 0
        self.total_dropped = 0
        self.startup_seconds_total = 0.0
        self.started_total = 0
        self.resource_limit_rejections = 0

    async def start(self) -> None:
        if hasattr(self.bridge, "recover"):
            failures = await self.bridge.recover()
            if isinstance(failures, int):
                self.cleanup_failures += failures
        self.reaper = asyncio.create_task(self._reap())

    async def close(self) -> None:
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        for session in list(self.sessions.values()):
            await self.stop(session, "backend_shutdown")
        self.tickets.clear()

    def metrics(self) -> dict[str, float]:
        return {
            "active_sessions": sum(s.state in ACTIVE for s in self.sessions.values()),
            "active_controllers": sum(s.control for s in self.sessions.values()),
            "active_viewers": sum(s.attached and s.state in ACTIVE for s in self.sessions.values()),
            "resource_limit_rejections": self.resource_limit_rejections,
            "session_failures": self.failures,
            "cleanup_failures": self.cleanup_failures,
            "bytes_transferred": self.total_bytes,
            "dropped_frames": self.total_dropped,
            "startup_seconds_total": self.startup_seconds_total,
            "sessions_started": self.started_total,
        }

    async def _reap(self) -> None:
        last_recovery = time.monotonic()
        while True:
            await asyncio.sleep(1)
            now = time.time()
            if time.monotonic() - last_recovery >= 30 and hasattr(self.bridge, "retry_recovery"):
                failures = await self.bridge.retry_recovery()
                if isinstance(failures, int):
                    self.cleanup_failures += failures
                last_recovery = time.monotonic()
            self.tickets = {k: v for k, v in self.tickets.items() if v[2] > now}
            for session in list(self.sessions.values()):
                if session.state in ACTIVE:
                    try:
                        online = self.fleet.get(session.device_id).state == DeviceState.ONLINE
                    except Exception:
                        online = False
                    if not online:
                        await self.stop(session, "device_offline", SessionState.FAILED)
                        continue
                if (
                    session.state in ACTIVE
                    and now - session.last_activity > self.settings.screen_idle_seconds
                ):
                    await self.stop(session, "idle_timeout", SessionState.TIMED_OUT)
                elif session.state not in ACTIVE and now - session.last_activity > 300:
                    self.sessions.pop(session.id, None)

    async def create(self, device_id: str, actor: Actor, config: ScreenConfig) -> Session:
        await self.security.authorize_device(actor, device_id, "screen:view")
        device = self.fleet.get(device_id)
        if device.state != DeviceState.ONLINE:
            raise HTTPException(409, "Device is offline")
        if DeviceCapability.ADB_SHELL not in device.capabilities:
            raise HTTPException(409, "Authorized ADB shell capability is unavailable")
        if device.sdk is not None and device.sdk < 21:
            raise HTTPException(409, "Screen streaming requires Android 5 or newer")
        async with self.lock:
            terminal = [s for s in self.sessions.values() if s.state not in RESERVED]
            for old in sorted(terminal, key=lambda item: item.created_at)[:-100]:
                self.sessions.pop(old.id, None)
            active = [s for s in self.sessions.values() if s.state in RESERVED]
            if (
                len(active) >= self.settings.screen_max_sessions
                or sum(s.device_id == device_id for s in active)
                >= self.settings.screen_max_per_device
                or sum(s.owner.identity == actor.identity for s in active)
                >= self.settings.screen_max_per_user
            ):
                self.resource_limit_rejections += 1
                raise HTTPException(429, "Screen session capacity exceeded")
            session = Session(
                str(uuid.uuid4()),
                device_id,
                actor,
                config,
                queue=asyncio.Queue(self.settings.screen_queue_frames),
            )
            self.sessions[session.id] = session
            session.task = asyncio.create_task(self._run(session, device.serial))
        await self.audit(session, "screen.session.start")
        return session

    async def audit(self, session: Session, action: str, *, error: str | None = None) -> None:
        await self.security.audit(
            session.owner,
            session.device_id,
            action,
            session.id,
            "allowed",
            "failed" if error else "succeeded",
            error=error,
        )

    async def get(self, sid: str, actor: Actor, *, terminate: bool = False) -> Session:
        session = self.sessions.get(sid)
        if session is None:
            raise HTTPException(404, "Screen session not found")
        await self.security.authorize_device(
            actor, session.device_id, "screen:session:terminate" if terminate else "screen:view"
        )
        if actor.identity != session.owner.identity and not (
            terminate and actor.role == "administrator"
        ):
            await self.security.audit(
                actor,
                session.device_id,
                "screen.session.access",
                sid,
                "denied",
                "rejected",
                error="session_owner_mismatch",
            )
            raise HTTPException(403, "Session belongs to another actor")
        return session

    async def acquire(self, session: Session, actor: Actor) -> None:
        await self.get(session.id, actor)
        await self.security.authorize_device(actor, session.device_id, "screen:control")
        async with self.lock:
            if session.state != SessionState.STREAMING or not session.attached:
                raise HTTPException(409, "Stream is not connected")
            if any(
                s.control and s.device_id == session.device_id and s.id != session.id
                for s in self.sessions.values()
            ):
                raise HTTPException(409, "Device already has a controller")
            session.control = True
            session.last_activity = time.time()
        await self.audit(session, "screen.control.acquire")

    async def release(self, session: Session) -> None:
        # Keep ownership reserved while cancelling held input, but never hold the
        # global manager lock across device I/O: a stalled phone must not block
        # control acquisition on an independent device.
        async with session.input_lock:
            if not session.control:
                return
            try:
                async with asyncio.timeout(3):
                    if session.pointer and session.stream:
                        await session.stream.send_input({**session.pointer, "action": "cancel"})
                    for key in session.held_keys:
                        await session.stream.send_input(
                            {"type": "key", "action": "up", "keycode": key}
                        )
            except Exception:
                self.cleanup_failures += 1
            finally:
                async with self.lock:
                    session.control = False
                session.pointer = None
                session.held_keys.clear()
        await self.audit(session, "screen.control.release")

    async def input(self, session: Session, actor: Actor, event: InputEvent) -> None:
        await self.security.authorize_device(actor, session.device_id, "screen:control")
        async with session.input_lock:
            if (
                actor.identity != session.owner.identity
                or not session.control
                or session.state != SessionState.STREAMING
            ):
                await self.security.audit(
                    actor,
                    session.device_id,
                    "screen.input",
                    session.id,
                    "denied",
                    "rejected",
                    error="control_not_owned",
                )
                raise HTTPException(403, "Exclusive control required")
            now = time.monotonic()
            if now - session.rate_started >= 1:
                session.rate_started, session.rate_count = now, 0
            session.rate_count += 1
            if session.rate_count > 120:
                raise HTTPException(429, "Control event rate exceeded")
            dimensions = (session.stream.width, session.stream.height)
            if event.type == "pointer" and (event.width, event.height) != dimensions:
                raise HTTPException(409, "Display dimensions changed")
            payload = event.model_dump(exclude_none=True)
            await session.stream.send_input(payload)
            if event.type == "pointer":
                session.pointer = payload if event.action in {"down", "move"} else None
            elif event.type == "key" and event.keycode is not None:
                if event.action == "down":
                    session.held_keys.add(event.keycode)
                else:
                    session.held_keys.discard(event.keycode)
            session.last_activity = time.time()

    async def ticket(self, session: Session, actor: Actor) -> dict[str, Any]:
        await self.get(session.id, actor)
        if session.state not in ACTIVE or session.attached:
            raise HTTPException(409, "Session unavailable or already connected")
        # One outstanding credential per session prevents unbounded token issuance.
        self.tickets = {
            k: v for k, v in self.tickets.items() if v[0] != session.id and v[2] > time.time()
        }
        value = secrets.token_urlsafe(32)
        self.tickets[value] = session.id, actor, time.time() + 30
        return {"ticket": value, "expires_in": 30}

    async def attach(self, sid: str, ticket: str) -> Session:
        entry = self.tickets.pop(ticket, None)
        if entry is None or entry[0] != sid or entry[2] < time.time():
            await self.security.audit(
                Actor("unauthenticated", "none", frozenset()),
                None,
                "screen.stream.connect",
                sid,
                "denied",
                "rejected",
                error="invalid_stream_ticket",
            )
            raise HTTPException(403, "Invalid stream ticket")
        session = await self.get(sid, entry[1])
        if session.attached or session.state not in ACTIVE:
            raise HTTPException(409, "Session unavailable")
        session.attached = True
        session.last_activity = time.time()
        return session

    async def stop(
        self,
        session: Session,
        reason: str = "user_stopped",
        state: SessionState = SessionState.STOPPED,
    ) -> None:
        async with session.stop_lock:
            await self._stop(session, reason, state)

    async def _stop(self, session: Session, reason: str, state: SessionState) -> None:
        if session.state not in ACTIVE and session.state != SessionState.STOPPING:
            return
        session.state = SessionState.STOPPING
        await self.release(session)
        task = session.task
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if session.stream:
            try:
                await session.stream.close()
            except Exception:
                self.cleanup_failures += 1
        session.state = state
        session.attached = False
        session.stream = None
        if state == SessionState.FAILED:
            self.failures += 1
        session.termination_reason = reason
        session.last_activity = time.time()
        for key in [k for k, v in self.tickets.items() if v[0] == session.id]:
            self.tickets.pop(key, None)
        while not session.queue.empty():
            session.queue.get_nowait()
        session.codec_packet = None
        self._enqueue(session, {"type": "status", "state": state, "reason": reason})
        await self.audit(session, "screen.session.stop")

    def _enqueue(self, session: Session, message: bytes | dict[str, Any]) -> None:
        if session.queue.full():
            self._record_drop(session, session.queue.get_nowait())
        session.queue.put_nowait(message)

    def _record_drop(self, session: Session, message: bytes | dict[str, Any]) -> None:
        # Only encoded video access units are frames; configuration and status
        # messages share the bounded queue but must not inflate this counter.
        if isinstance(message, bytes) and len(message) >= 12 and not (message[0] & 0x80):
            session.dropped_frames += 1
            self.total_dropped += 1

    async def _run(self, session: Session, serial: str) -> None:
        try:
            async with asyncio.timeout(20):
                session.stream = await self.bridge.start(serial, session.config)
            session.state = SessionState.STREAMING
            session.startup_seconds = time.time() - session.created_at
            self.startup_seconds_total += session.startup_seconds
            self.started_total += 1
            if session.reconnect_attempts:
                self._enqueue(
                    session,
                    {"type": "status", "state": "streaming", "control": False},
                )
            self._enqueue(
                session,
                {
                    "type": "metadata",
                    "width": session.stream.width,
                    "height": session.stream.height,
                    "codec": "h264",
                },
            )
            dimensions = (session.stream.width, session.stream.height)
            async for packet in session.stream.packets():
                current_dimensions = (session.stream.width, session.stream.height)
                if current_dimensions != dimensions and all(current_dimensions):
                    dimensions = current_dimensions
                    async with session.input_lock:
                        if session.pointer:
                            # Rotation invalidates a held gesture. Cancel against
                            # the new surface rather than retaining stale input.
                            pointer = session.pointer
                            session.pointer = None
                            await session.stream.send_input(
                                {
                                    **pointer,
                                    "action": "cancel",
                                    "width": dimensions[0],
                                    "height": dimensions[1],
                                    "x": min(pointer["x"], dimensions[0] - 1),
                                    "y": min(pointer["y"], dimensions[1] - 1),
                                }
                            )
                    self._enqueue(
                        session,
                        {
                            "type": "metadata",
                            "width": dimensions[0],
                            "height": dimensions[1],
                            "codec": "h264",
                        },
                    )
                if self.fleet.get(session.device_id).state != DeviceState.ONLINE:
                    raise ConnectionError("Device offline")
                wire = packet.wire()
                if packet.config:
                    session.codec_packet = wire
                if session.queue.full():
                    session.dropping = True
                    while not session.queue.empty():
                        self._record_drop(session, session.queue.get_nowait())
                if session.dropping:
                    if not packet.keyframe:
                        if not packet.config:
                            self._record_drop(session, wire)
                        continue
                    session.dropping = False
                    if session.codec_packet:
                        self._enqueue(session, session.codec_packet)
                self._enqueue(session, wire)
            raise ConnectionError("Stream ended")
        except asyncio.CancelledError:
            raise
        except Exception:
            if session.state not in ACTIVE:
                return
            await self.release(session)
            if session.stream:
                try:
                    await session.stream.close()
                except Exception:
                    self.cleanup_failures += 1
                finally:
                    session.stream = None
            attempts = getattr(session, "reconnect_attempts", 0)
            if attempts < 2 and session.state in ACTIVE:
                session.reconnect_attempts = attempts + 1
                session.state = SessionState.RECONNECTING
                while not session.queue.empty():
                    session.queue.get_nowait()
                session.dropping = False
                session.codec_packet = None
                self._enqueue(
                    session, {"type": "status", "state": "reconnecting", "control": False}
                )
                await asyncio.sleep(1)
                await self._run(session, serial)
            else:
                await self.stop(session, "stream_failed", SessionState.FAILED)
