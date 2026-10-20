"""Single-use ticket authentication precedes WebSocket acceptance."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from android_fleet.api.metric_models import HistoryResponse, history_response
from android_fleet.devices.registry import DeviceNotFound
from android_fleet.metrics.history import InvalidHistoryQuery
from android_fleet.security import Actor
from android_fleet.terminal.manager import Session, TerminalManager
from android_fleet.terminal.models import SessionState, TerminalConfig, TerminalMessage


def router(manager: TerminalManager, security: Any) -> APIRouter:
    api = APIRouter(prefix="/api/v1/terminal")

    async def authorize(request: Request, permission: str) -> Actor:
        try:
            return await security.authorize(request, permission)  # type: ignore[no-any-return]
        except HTTPException:
            manager.authentication_failures += 1
            raise

    @api.post("/sessions", status_code=201)
    async def create(body: TerminalConfig, request: Request) -> dict[str, Any]:
        actor = await authorize(request, "terminal:" + body.connection_type)
        try:
            return (await manager.create(actor, body)).public()
        except DeviceNotFound as exc:
            manager.failures += 1
            await security.audit(
                actor,
                body.device_id,
                "terminal.create",
                str(uuid.uuid4()),
                "allowed",
                "rejected",
                error="device_not_found",
            )
            raise HTTPException(404, "Device not found") from exc
        except HTTPException as exc:
            if exc.status_code != 502:
                manager.failures += 1
                denied = exc.status_code == 403
                if denied:
                    manager.authentication_failures += 1
                await security.audit(
                    actor,
                    body.device_id,
                    "terminal.create",
                    str(uuid.uuid4()),
                    "denied" if denied else "allowed",
                    "rejected",
                    error="permission_denied" if denied else "creation_rejected",
                )
            raise

    @api.get("/sessions")
    async def history(request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "terminal:view")
        return {"items": await manager.history(actor)}

    @api.get("/sessions/{sid}/telemetry")
    async def telemetry(
        sid: str,
        request: Request,
        metric: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=1000, ge=1, le=10000),
        cursor: str | None = Query(default=None, max_length=4096),
        end: datetime | None = None,
    ) -> HistoryResponse:
        actor = await authorize(request, "telemetry.read")
        item = await manager.recording_metadata(sid, actor)
        if not item.get("device_recording", {}).get("enabled"):
            raise HTTPException(409, "Device statistics were not recorded for this session")
        start = datetime.fromtimestamp(item["created_at"], UTC)
        # Pin 'end' across pages; active runs use the caller's first-page timestamp.
        finish = (
            datetime.fromtimestamp(item["ended_at"], UTC) if item["ended_at"] else datetime.now(UTC)
        )
        finish += timedelta(microseconds=1)
        if end is not None:
            if end.tzinfo is None:
                raise HTTPException(422, "End timestamp must include a timezone")
            finish = min(finish, end)
        try:
            page = await manager.recordings.query(
                sid, start=start, end=finish, metric=metric, limit=limit, cursor=cursor
            )
        except InvalidHistoryQuery as exc:
            raise HTTPException(422, str(exc)) from exc
        return history_response(item["device_id"], start, finish, page)

    @api.get("/sessions/{sid}")
    async def detail(sid: str, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "terminal:view")
        return (await manager.get(sid, actor)).public()

    @api.delete("/sessions/{sid}")
    async def close(sid: str, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "terminal:view")
        session = await manager.get(sid, actor)
        await manager.stop(session)
        return session.public()

    @api.post("/sessions/{sid}/terminate")
    async def terminate(sid: str, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "terminal:session:terminate")
        session = await manager.get(sid, actor, terminate=True)
        await manager.stop(session, "administrator_terminated")
        await security.audit(
            actor, session.device_id, "terminal.admin_terminate", sid, "allowed", "completed"
        )
        return session.public()

    @api.post("/sessions/{sid}/ticket")
    async def ticket(sid: str, request: Request) -> dict[str, Any]:
        actor = await authorize(request, "terminal:view")
        return await manager.ticket(await manager.get(sid, actor), actor)

    @api.websocket("/sessions/{sid}/stream")
    async def stream(sid: str, socket: WebSocket) -> None:
        session: Session | None = None
        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[str] | None = None
        reason = "browser_disconnected"
        try:
            if socket.headers.get("origin") not in manager.settings.terminal_allowed_origins:
                manager.authentication_failures += 1
                raise HTTPException(403, "Untrusted origin")
            protocols = [
                p.strip() for p in socket.headers.get("sec-websocket-protocol", "").split(",")
            ]
            tokens = [p.removeprefix("ticket.") for p in protocols if p.startswith("ticket.")]
            if "fleet-terminal.v1" not in protocols or len(tokens) != 1 or len(tokens[0]) > 128:
                manager.authentication_failures += 1
                raise HTTPException(403, "Invalid handshake")
            session = await manager.attach(sid, tokens[0])
            await socket.accept(subprotocol="fleet-terminal.v1")
            await socket.send_json({"version": 1, "type": "status", "state": session.state})
            current = session

            async def send() -> None:
                while True:
                    message = await current.queue.get()
                    await manager.authorize(current, current.owner)
                    async with asyncio.timeout(5):
                        await socket.send_json(message)
                    if message["type"] == "status" and message["state"] in {
                        "closed",
                        "failed",
                        "timed_out",
                    }:
                        await socket.close(code=1000)
                        return

            sender = asyncio.create_task(send())
            while True:
                receiver = asyncio.create_task(socket.receive_text())
                done, _ = await asyncio.wait(
                    {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                )
                if sender in done:
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
                    sender.result()
                    break
                raw = receiver.result()
                if len(raw.encode()) > 4096:
                    raise ValueError("Message too large")
                message = TerminalMessage.model_validate_json(raw)
                await manager.input(current, message)
        except (
            HTTPException,
            ValueError,
            ValidationError,
            TimeoutError,
            RuntimeError,
            OSError,
            KeyError,
            WebSocketDisconnect,
        ) as exc:
            if isinstance(exc, (ValueError, ValidationError, KeyError)):
                reason = "invalid_message"
            elif isinstance(exc, HTTPException):
                reason = "input_rate_limited" if exc.status_code == 429 else "authorization_denied"
            elif isinstance(exc, TimeoutError):
                reason = "transport_timeout"
            elif isinstance(exc, (RuntimeError, OSError)):
                reason = "transport_failed"
            if session is None:
                await security.audit(
                    Actor("unauthenticated", "none", frozenset()),
                    None,
                    "terminal.attach",
                    sid,
                    "denied",
                    "rejected",
                    error="invalid_handshake",
                )
            try:
                if session is not None and reason != "browser_disconnected":
                    if sender:
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
                    async with asyncio.timeout(5):
                        await socket.send_json(
                            {
                                "version": 1,
                                "type": "error",
                                "code": reason,
                                "detail": {
                                    "invalid_message": "Terminal message was invalid.",
                                    "input_rate_limited": "Terminal input rate limit exceeded.",
                                    "authorization_denied": "Terminal authorization was denied.",
                                    "transport_timeout": "Terminal transport timed out.",
                                    "transport_failed": "Terminal transport failed.",
                                }.get(reason, "Terminal session failed."),
                            }
                        )
                await socket.close(code=1008)
            except (RuntimeError, WebSocketDisconnect, TimeoutError, OSError):
                pass
        finally:
            with CancelScope(shield=True):
                for task in (sender, receiver):
                    if task:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                if session:
                    session.attached = False
                    if reason != "browser_disconnected":
                        manager.runtime_failures += 1
                        await manager.stop(session, reason, SessionState.FAILED)

    return api
