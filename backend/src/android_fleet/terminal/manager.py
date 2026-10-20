"""Application-owned terminals, bounded replay and opt-in durable run reports."""

import asyncio
import codecs
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from android_fleet.adb.base import TerminalTransport
from android_fleet.devices.models import DeviceCapability, DeviceState
from android_fleet.devices.registry import _thread_operation
from android_fleet.metrics.history import MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot
from android_fleet.security import Actor
from android_fleet.terminal.models import SessionState, TerminalConfig, TerminalMessage

ACTIVE = {SessionState.CONNECTING, SessionState.ACTIVE, SessionState.DISCONNECTING}


@dataclass
class Session:
    id: str
    owner: Actor
    config: TerminalConfig
    device_id: str | None = None
    state: SessionState = SessionState.CONNECTING
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    termination_reason: str | None = None
    last_activity: float = field(default_factory=time.monotonic)
    transport: TerminalTransport | None = None
    task: asyncio.Task[None] | None = None
    attached: bool = False
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=16))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    rate_start: float = field(default_factory=time.monotonic)
    recording_task: asyncio.Task[None] | None = None
    sample_count: int = 0
    recording_error: str | None = None
    available_metrics: set[str] = field(default_factory=set)
    last_sample_at: datetime | None = None
    output: str = ""
    output_truncated: bool = False
    rate_bytes: int = 0
    rate_messages: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "device_recording": {
                "enabled": self.config.record_device,
                "interval_seconds": self.config.sample_interval,
                "sample_count": self.sample_count,
                "last_error": self.recording_error,
                "available_metrics": sorted(self.available_metrics),
            },
            "command": self.config.command,
            "output": self.output if self.config.command else None,
            "output_truncated": self.output_truncated,
            "id": self.id,
            "owner": self.owner.identity,
            "connection_type": self.config.connection_type,
            "device_id": self.device_id,
            "profile_id": self.config.profile_id,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "state": self.state,
            "duration": (self.ended_at or time.time()) - self.created_at,
            "termination_reason": self.termination_reason,
        }


class TerminalManager:
    def __init__(self, settings: Any, service: Any, security: Any, ssh_gateway: Any) -> None:
        self.settings, self.service, self.security, self.ssh_gateway = (
            settings,
            service,
            security,
            ssh_gateway,
        )
        self.sessions: dict[str, Session] = {}
        self.tickets: dict[str, tuple[str, Actor, float]] = {}
        self.lock = asyncio.Lock()
        self.reaper: asyncio.Task[None] | None = None
        self.failures = self.authentication_failures = self.cleanup_failures = self.timeouts = 0
        self.runtime_failures = 0
        self.duration_total = 0.0
        self.closed_total = 0
        configured = getattr(settings, "terminal_path", None)
        self.path = Path(configured or Path(settings.registry_path).parent / "terminals.sqlite3")

        self.recordings = MetricHistoryStore(
            self.path.with_name(self.path.stem + "-telemetry.sqlite3"),
            retention_seconds=getattr(settings, "history_retention_seconds", 604800),
            max_points=getattr(settings, "history_max_points", 1_000_000),
        )

    async def initialize(self) -> None:
        def setup() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS terminal_sessions("
                    "id TEXT PRIMARY KEY, actor TEXT NOT NULL, metadata TEXT NOT NULL)"
                )
                rows = db.execute("SELECT id,metadata FROM terminal_sessions").fetchall()
                for sid, raw in rows:
                    item = json.loads(raw)
                    if item["state"] in ACTIVE:
                        item.update(
                            state="closed",
                            ended_at=time.time(),
                            termination_reason="backend_restart",
                        )
                        item["duration"] = item["ended_at"] - item["created_at"]
                        db.execute(
                            "UPDATE terminal_sessions SET metadata=? WHERE id=?",
                            (json.dumps(item), sid),
                        )
            self.path.chmod(0o600)

        await asyncio.to_thread(setup)
        await self.recordings.initialize()
        self.reaper = asyncio.create_task(self._reap())

    async def _save(self, session: Session) -> None:
        data = json.dumps(session.public())

        def save() -> None:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "INSERT OR REPLACE INTO terminal_sessions VALUES(?,?,?)",
                    (session.id, session.owner.identity, data),
                )

        await _thread_operation(save)

    async def history(self, actor: Actor) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            with sqlite3.connect(self.path) as db:
                rows = db.execute(
                    "SELECT metadata FROM terminal_sessions WHERE actor=? "
                    "ORDER BY rowid DESC LIMIT 100",
                    (actor.identity,),
                ).fetchall()
            return [json.loads(row[0]) for row in rows]

        records = await asyncio.to_thread(read)
        records = [
            self.sessions[item["id"]].public() if item["id"] in self.sessions else item
            for item in records
        ]
        return [
            item
            for item in records
            if actor.device_ids is None or item.get("device_id") in actor.device_ids
        ]

    async def authorize(self, session: Session, actor: Actor) -> None:
        permission = "terminal:" + session.config.connection_type
        if (
            actor.identity != session.owner.identity
            or permission not in actor.permissions
            or actor.identity == "anonymous"
        ):
            await self.security.audit(
                actor,
                session.device_id,
                "terminal.attach",
                session.id,
                "denied",
                "rejected",
                error="permission_denied",
            )
            self.authentication_failures += 1
            raise HTTPException(403, "Permission denied")
        if session.device_id:
            await self.security.authorize_device(actor, session.device_id, permission)
        if session.config.connection_type == "ssh":
            await self.ssh_gateway.authorize(session.config.profile_id, actor)

    async def create(self, actor: Actor, config: TerminalConfig) -> Session:
        permission = "terminal:" + config.connection_type
        if permission not in actor.permissions or actor.identity == "anonymous":
            raise HTTPException(403, "Permission denied")
        device_id = config.device_id
        serial = ""
        if config.connection_type == "adb":
            if not self.settings.terminal_adb_enabled:
                raise HTTPException(403, "Interactive ADB shell is disabled")
            assert device_id is not None
            await self.security.authorize_device(actor, device_id, permission)
            device = self.service.get(device_id)
            if (
                device.state != DeviceState.ONLINE
                or DeviceCapability.ADB_SHELL not in device.capabilities
            ):
                raise HTTPException(409, "Authorized online shell capability unavailable")
            serial = device.serial
            if (await self.service.adb.list_devices()).get(serial) != DeviceState.ONLINE:
                raise HTTPException(409, "Device is offline or unauthorized")
        else:
            await self.ssh_gateway.authorize(config.profile_id, actor)
            profile = await self.ssh_gateway.profiles.get(config.profile_id)
            device_id = profile.device_id
            if device_id:
                await self.security.authorize_device(actor, device_id, permission)
        if config.record_device:
            if not device_id:
                raise HTTPException(409, "Link the SSH profile to an Android device to record it")
            await self.security.authorize_device(actor, device_id, "telemetry.read")
            device = self.service.get(device_id)
            if (
                device.state != DeviceState.ONLINE
                or DeviceCapability.ADB_SHELL not in device.capabilities
            ):
                raise HTTPException(
                    409, "Device recording requires an online authenticated ADB device"
                )
        async with self.lock:
            active = [s for s in self.sessions.values() if s.state in ACTIVE]
            if (
                len(active) >= self.settings.terminal_max_sessions
                or sum(s.owner.identity == actor.identity for s in active)
                >= self.settings.terminal_max_per_user
                or (
                    device_id
                    and sum(s.device_id == device_id for s in active)
                    >= self.settings.terminal_max_per_device
                )
            ):
                raise HTTPException(429, "Terminal session limit reached")
            session = Session(str(uuid.uuid4()), actor, config, device_id)
            session.queue = asyncio.Queue(maxsize=self.settings.terminal_queue_chunks)
            self.sessions[session.id] = session
        await self._save(session)
        await self.security.audit(
            actor, device_id, "terminal.create", session.id, "allowed", "started"
        )
        try:
            if config.record_device:
                await self._record_sample(session)
            async with asyncio.timeout(20):
                session.transport = (
                    await self.service.adb.terminal(serial, config.cols, config.rows)
                    if config.connection_type == "adb"
                    else await self.ssh_gateway.open(
                        config.profile_id, actor, config.cols, config.rows, config.command
                    )
                )
            if session.state != SessionState.CONNECTING:
                await session.transport.close()
                raise HTTPException(409, "Session terminated during connection")
            session.state = SessionState.ACTIVE
            await self._save(session)
            session.task = asyncio.create_task(self._read(session))
            if config.record_device:
                session.recording_task = asyncio.create_task(self._record(session))
        except asyncio.CancelledError:
            await self.stop(session, "connection_cancelled", SessionState.FAILED)
            raise
        except Exception:
            self.failures += 1
            await self.stop(session, "connection_failed", SessionState.FAILED)
            raise HTTPException(502, "Terminal connection failed") from None
        return session

    async def get(self, sid: str, actor: Actor, *, terminate: bool = False) -> Session:
        session = self.sessions.get(sid)
        if session is None:
            raise HTTPException(404, "Session not found")
        if (
            terminate
            and "terminal:session:terminate" in actor.permissions
            and actor.role == "administrator"
        ):
            if session.device_id:
                await self.security.authorize_device(
                    actor, session.device_id, "terminal:session:terminate"
                )
            return session
        await self.authorize(session, actor)
        return session

    async def ticket(self, session: Session, actor: Actor) -> dict[str, Any]:
        await self.authorize(session, actor)
        if session.state != SessionState.ACTIVE or session.attached:
            raise HTTPException(409, "Session cannot be attached")
        token = secrets.token_urlsafe(32)
        expiry = time.time() + 30
        self.tickets = {k: v for k, v in self.tickets.items() if v[0] != session.id}
        self.tickets[token] = (session.id, actor, expiry)
        return {"ticket": token, "expires_at": expiry, "protocol": "fleet-terminal.v1"}

    async def attach(self, sid: str, ticket: str) -> Session:
        async with self.lock:
            item = self.tickets.pop(ticket, None)
            if not item or item[0] != sid or item[2] < time.time():
                self.authentication_failures += 1
                raise HTTPException(403, "Invalid ticket")
            session = await self.get(sid, item[1])
            if session.attached or session.state != SessionState.ACTIVE:
                raise HTTPException(409, "Session cannot be attached")
            session.attached = True
            session.last_activity = time.monotonic()
            while not session.queue.empty():
                session.queue.get_nowait()
            if session.output:
                session.queue.put_nowait({"version": 1, "type": "output", "data": session.output})
            return session

    async def input(self, session: Session, message: TerminalMessage) -> None:
        await self.authorize(session, session.owner)
        if session.state != SessionState.ACTIVE or session.transport is None:
            raise HTTPException(409, "Session closed")
        now = time.monotonic()
        if now - session.rate_start >= 1:
            session.rate_start, session.rate_bytes, session.rate_messages = now, 0, 0
        session.rate_bytes += len((message.data or "").encode())
        session.rate_messages += 1
        if session.rate_bytes > 65536 or session.rate_messages > 100:
            raise HTTPException(429, "Input rate limit exceeded")
        async with asyncio.timeout(5):
            if message.type == "input":
                await session.transport.write((message.data or "").encode())
                session.last_activity = now
            elif message.type == "resize":
                assert message.cols is not None and message.rows is not None
                await session.transport.resize(message.cols, message.rows)
            elif message.type == "close":
                await self.stop(session, "client_closed")
            elif message.type == "heartbeat":
                await asyncio.wait_for(session.queue.put({"version": 1, "type": "heartbeat"}), 5)

    async def _read(self, session: Session) -> None:
        assert session.transport is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while chunk := await session.transport.read():
                data = decoder.decode(chunk)
                combined = session.output + data
                session.output_truncated |= len(combined) > 65536
                session.output = combined[-65536:]
                if session.config.command:
                    await self._save(session)
                if session.queue.full():
                    session.queue.get_nowait()
                session.queue.put_nowait({"version": 1, "type": "output", "data": data})
            if session.config.record_device:
                # Capture the end boundary as well as the pre-command baseline.
                # Drain the periodic sampler first so one sample is never counted twice.
                if session.recording_task:
                    session.recording_task.cancel()
                    await asyncio.gather(session.recording_task, return_exceptions=True)
                await self._record_sample(session)
            await self.stop(session, "remote_closed")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.runtime_failures += 1
            await self.stop(session, "transport_failed", SessionState.FAILED)

    async def recording_metadata(self, sid: str, actor: Actor) -> dict[str, Any]:
        """Authorize saved telemetry even after a closed session leaves memory."""
        if sid in self.sessions:
            session = await self.get(sid, actor)
            if session.device_id:
                await self.security.authorize_device(actor, session.device_id, "telemetry.read")
            return session.public()

        def read() -> dict[str, Any] | None:
            with sqlite3.connect(self.path) as db:
                row = db.execute(
                    "SELECT metadata FROM terminal_sessions WHERE id=? AND actor=?",
                    (sid, actor.identity),
                ).fetchone()
            return json.loads(row[0]) if row else None

        item = await asyncio.to_thread(read)
        if item is None:
            raise HTTPException(404, "Session not found")
        restored = Session(
            sid,
            actor,
            TerminalConfig(
                connection_type=item["connection_type"],
                device_id=item["device_id"] if item["connection_type"] == "adb" else None,
                profile_id=item["profile_id"],
            ),
            item["device_id"],
        )
        await self.authorize(restored, actor)
        if restored.device_id:
            await self.security.authorize_device(actor, restored.device_id, "telemetry.read")
        return item

    async def _record_sample(self, session: Session) -> None:
        assert session.device_id is not None
        try:
            await self.authorize(session, session.owner)
            await self.security.authorize_device(session.owner, session.device_id, "telemetry.read")
            sample = await self.service.sample_device(session.device_id)
            if sample is None:
                session.recording_error = (
                    "Device offline or observation invalidated; leaving a gap."
                )
            elif session.last_sample_at != sample.observed_at:
                # The run ID is the isolated source key in the recording store;
                # normal device history retains the original device ID.
                await self.recordings.append(
                    MetricSnapshot(session.id, sample.observed_at, sample.values)
                )
                session.last_sample_at = sample.observed_at
                session.sample_count += 1
                session.available_metrics.update(value.name for value in sample.values)
                session.recording_error = None if sample.values else "No accessible metric sources."
        except asyncio.CancelledError:
            raise
        except HTTPException:
            session.recording_error = "Device recording authorization was denied."
        except Exception:
            session.recording_error = (
                "Device sample could not be collected or saved; leaving a gap."
            )
        await self._save(session)

    async def _record(self, session: Session) -> None:
        while session.state == SessionState.ACTIVE:
            started = time.monotonic()
            await self._record_sample(session)
            await asyncio.sleep(
                max(0, session.config.sample_interval - (time.monotonic() - started))
            )

    async def stop(
        self,
        session: Session,
        reason: str = "user_closed",
        state: SessionState = SessionState.CLOSED,
    ) -> None:
        async with session.lock:
            if session.state not in ACTIVE:
                return
            session.state = SessionState.DISCONNECTING
            if session.recording_task:
                session.recording_task.cancel()
                await asyncio.gather(session.recording_task, return_exceptions=True)
            if session.task and session.task != asyncio.current_task():
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
            if session.transport:
                try:
                    async with asyncio.timeout(5):
                        await session.transport.close()
                except Exception:
                    self.cleanup_failures += 1
            session.state, session.termination_reason, session.ended_at = state, reason, time.time()
            self.duration_total += session.ended_at - session.created_at
            self.closed_total += 1
            if state == SessionState.TIMED_OUT:
                self.timeouts += 1
            self.tickets = {k: v for k, v in self.tickets.items() if v[0] != session.id}
            await self._save(session)
            await self.security.audit(
                session.owner,
                session.device_id,
                "terminal.terminate",
                session.id,
                "allowed",
                "failed" if state == SessionState.FAILED else "completed",
                duration=session.ended_at - session.created_at,
                error=reason,
            )

            while not session.queue.empty():
                session.queue.get_nowait()
            session.queue.put_nowait(
                {"version": 1, "type": "status", "state": state, "reason": reason}
            )

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(1)
            self.tickets = {k: v for k, v in self.tickets.items() if v[2] > time.time()}
            for session in list(self.sessions.values()):
                if session.state not in ACTIVE:
                    if session.ended_at and time.time() - session.ended_at > 300:
                        self.sessions.pop(session.id, None)
                    continue
                try:
                    await self.authorize(session, session.owner)
                except HTTPException:
                    await self.stop(session, "authorization_revoked", SessionState.FAILED)
                    continue
                if time.time() - session.created_at > self.settings.terminal_lifetime_seconds:
                    await self.stop(session, "lifetime_timeout", SessionState.TIMED_OUT)
                elif (
                    not session.config.command
                    and session.attached
                    and time.monotonic() - session.last_activity
                    > self.settings.terminal_idle_seconds
                ):
                    await self.stop(session, "idle_timeout", SessionState.TIMED_OUT)
                elif session.config.connection_type == "adb":
                    try:
                        online = self.service.get(session.device_id).state == DeviceState.ONLINE
                    except Exception:
                        online = False
                    if not online:
                        await self.stop(session, "device_disconnected", SessionState.FAILED)

    async def close(self) -> None:
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        for session in list(self.sessions.values()):
            await self.stop(session, "backend_shutdown")
        self.tickets.clear()
        await self.recordings.close()

    def metrics(self) -> dict[str, float]:
        return {
            "active_adb": sum(
                s.state in ACTIVE and s.config.connection_type == "adb"
                for s in self.sessions.values()
            ),
            "active_ssh": sum(
                s.state in ACTIVE and s.config.connection_type == "ssh"
                for s in self.sessions.values()
            ),
            "creation_failures": self.failures,
            "transport_failures": self.runtime_failures,
            "authentication_failures": self.authentication_failures,
            "cleanup_failures": self.cleanup_failures,
            "timeouts": self.timeouts,
            "duration_seconds_sum": self.duration_total,
            "duration_seconds_count": self.closed_total,
        }
