"""Authenticated REST negotiation and session-bound WebSocket video transport."""

import asyncio
import json
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from android_fleet.devices.registry import DeviceNotFound
from android_fleet.screen.manager import ScreenManager, Session
from android_fleet.screen.models import InputEvent, ScreenConfig


def router(manager: ScreenManager, security: Any) -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    async def owned(sid: str, request: Request, terminate: bool = False) -> Session:
        actor = await security.authorize(
            request, "screen:session:terminate" if terminate else "screen:view"
        )
        return await manager.get(sid, actor, terminate=terminate)

    @api.post("/devices/{device_id}/screen/sessions", status_code=201)
    async def create(device_id: str, body: ScreenConfig, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "screen:view")
        try:
            return (await manager.create(device_id, actor, body)).public()
        except DeviceNotFound as exc:
            raise HTTPException(404, "Device not found") from exc

    @api.get("/screen/sessions")
    async def active(request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "screen:view")
        if actor.identity == "anonymous":
            raise HTTPException(403, "Authenticated screen viewer required")
        return {
            "items": [
                s.public()
                for s in manager.sessions.values()
                if s.owner.identity == actor.identity
                and (actor.device_ids is None or s.device_id in actor.device_ids)
            ]
        }

    @api.get("/screen/sessions/{sid}")
    async def detail(sid: str, request: Request) -> dict[str, Any]:
        return (await owned(sid, request)).public()

    @api.get("/screen/sessions/{sid}/statistics")
    async def statistics(sid: str, request: Request) -> dict[str, Any]:
        return (await owned(sid, request)).public()["statistics"]  # type: ignore[no-any-return]

    @api.delete("/screen/sessions/{sid}")
    async def stop(sid: str, request: Request) -> dict[str, Any]:
        session = await owned(sid, request)
        await manager.stop(session)
        return session.public()

    @api.post("/screen/sessions/{sid}/terminate")
    async def terminate(sid: str, request: Request) -> dict[str, Any]:
        session = await owned(sid, request, True)
        await manager.stop(session, "administrator_terminated")
        return session.public()

    @api.post("/screen/sessions/{sid}/control")
    async def acquire(sid: str, request: Request) -> dict[str, Any]:
        session = await owned(sid, request)
        await manager.acquire(session, request.state.actor)
        return session.public()

    @api.delete("/screen/sessions/{sid}/control")
    async def release(sid: str, request: Request) -> dict[str, Any]:
        session = await owned(sid, request)
        await manager.release(session)
        return session.public()

    @api.post("/screen/sessions/{sid}/ticket")
    async def ticket(sid: str, request: Request) -> dict[str, Any]:
        session = await owned(sid, request)
        return await manager.ticket(session, request.state.actor)

    @api.websocket("/screen/sessions/{sid}/stream")
    async def stream(sid: str, socket: WebSocket) -> None:
        if socket.headers.get("origin") not in manager.settings.screen_allowed_origins:
            await socket.close(code=1008)
            await security.audit(
                NoneActor,
                None,
                "screen.stream.connect",
                sid,
                "denied",
                "rejected",
                error="untrusted_origin",
            )
            return
        await socket.accept()
        session: Session | None = None
        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[str] | None = None
        try:
            raw = await asyncio.wait_for(socket.receive_text(), timeout=5)
            if len(raw) > 512:
                raise ValueError("Invalid handshake")
            hello = json.loads(raw)
            if (
                not isinstance(hello, dict)
                or set(hello) != {"ticket"}
                or not isinstance(hello["ticket"], str)
            ):
                raise ValueError("Invalid handshake")
            session = await manager.attach(sid, hello["ticket"])
            current = session
            if current.stream is not None:
                await socket.send_json(
                    {
                        "type": "metadata",
                        "width": current.stream.width,
                        "height": current.stream.height,
                        "codec": "h264",
                    }
                )

            async def send() -> None:
                while True:
                    message = await current.queue.get()
                    async with asyncio.timeout(5):
                        if isinstance(message, bytes):
                            await socket.send_bytes(message)
                            current.bytes_transferred += len(message)
                            manager.total_bytes += len(message)
                        else:
                            await socket.send_json(message)
                            if message.get("type") == "status" and message.get("state") in {
                                "stopped",
                                "failed",
                                "timed_out",
                            }:
                                await socket.close(code=1000)
                                return

            sender = asyncio.create_task(send())
            while True:
                receiver = asyncio.create_task(socket.receive_text())
                done, _ = await asyncio.wait(
                    {receiver, sender}, return_when=asyncio.FIRST_COMPLETED
                )
                if sender in done:
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
                    sender.result()
                    break
                raw = receiver.result()
                if len(raw) > 4096:
                    raise ValueError("Input too large")
                payload = json.loads(raw)
                if payload == {"type": "ping"}:
                    await security.authorize_device(current.owner, current.device_id, "screen:view")
                    import time

                    current.last_activity = time.time()
                    continue
                try:
                    event = InputEvent.model_validate(payload)
                    await manager.input(current, current.owner, event)
                except (HTTPException, ValidationError) as exc:
                    if isinstance(exc, ValidationError):
                        await security.audit(
                            current.owner,
                            current.device_id,
                            "screen.input",
                            sid,
                            "denied",
                            "rejected",
                            error="invalid_input",
                        )
                    await socket.send_json(
                        {
                            "type": "error",
                            "detail": exc.detail
                            if isinstance(exc, HTTPException)
                            else "Invalid input",
                        }
                    )
        except (WebSocketDisconnect, HTTPException, ValueError, TimeoutError, RuntimeError):
            try:
                await socket.close(code=1008)
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            with CancelScope(shield=True):
                if receiver:
                    if not receiver.done():
                        receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
                if sender:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
                if session:
                    session.attached = False
                    await manager.stop(session, "browser_disconnected")

    return api


from android_fleet.security import Actor  # noqa: E402

NoneActor = Actor("unauthenticated", "none", frozenset())
