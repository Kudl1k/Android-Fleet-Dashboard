"""Permission-enforced control API; artifacts never use public static serving."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from android_fleet.control.manager import PERMISSIONS, Manager, validate_apk
from android_fleet.devices.registry import DeviceNotFound


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(max_length=64)
    package: str | None = Field(default=None, max_length=255)
    property: str | None = Field(default=None, max_length=128)
    confirmed: StrictBool = False


def router(manager: Manager, security: Any) -> APIRouter:
    api = APIRouter(prefix="/api/v1")
    manager.security = security

    @api.post("/devices/{device_id}/operations", status_code=202)
    async def submit(device_id: str, body: OperationRequest, request: Request) -> dict[str, Any]:
        request.state.audit_action = (
            body.action if body.action in PERMISSIONS else "control.unknown"
        )
        actor = await security.authorize(request, PERMISSIONS.get(body.action, "control.unknown"))
        try:
            op = await manager.submit(
                device_id,
                body.action,
                actor,
                package=body.package,
                property=body.property,
                confirmed=body.confirmed,
            )
        except (ValueError, DeviceNotFound) as exc:
            await security.audit(
                actor,
                device_id,
                body.action,
                request.state.request_id,
                "allowed",
                "rejected",
                error="invalid_operation_request",
            )
            raise HTTPException(404 if isinstance(exc, DeviceNotFound) else 400, str(exc)) from exc
        await security.audit(actor, device_id, body.action, op["id"], "allowed", "queued")
        return op

    @api.get("/operations")
    async def history(
        request: Request,
        device_id: str | None = None,
        action: str | None = None,
        state: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        await security.authorize(request, "operations.read")
        return manager.history(
            device_id=device_id, action=action, state=state, limit=limit, offset=offset
        )

    def get(operation_id: str) -> dict[str, Any]:
        try:
            return manager.get(operation_id)
        except KeyError as exc:
            raise HTTPException(404, "Operation not found") from exc

    @api.get("/operations/{operation_id}")
    async def status(operation_id: str, request: Request) -> dict[str, Any]:
        await security.authorize(request, "operations.read")
        return get(operation_id)

    @api.post("/operations/{operation_id}/cancel")
    async def cancel(operation_id: str, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "operations.cancel")
        op = get(operation_id)
        if actor.role != "administrator" and actor.identity != op["actor"]:
            await security.audit(
                actor,
                op["device_id"],
                "operations.cancel",
                operation_id,
                "denied",
                "rejected",
                error="operation_actor_mismatch",
            )
            raise HTTPException(403, "Operation belongs to another actor")
        try:
            result = await manager.cancel(operation_id)
        except ValueError as exc:
            await security.audit(
                actor,
                op["device_id"],
                "operations.cancel",
                operation_id,
                "allowed",
                "rejected",
                error="operation_not_cancellable",
            )
            raise HTTPException(409, str(exc)) from exc
        await security.audit(
            actor, op["device_id"], "operations.cancel", operation_id, "allowed", "succeeded"
        )
        return result

    @api.post("/devices/{device_id}/apk", status_code=202)
    async def upload(device_id: str, request: Request) -> dict[str, Any]:
        request.state.audit_action = "apps.install"
        actor = await security.authorize(request, "apps.install")
        path: Path | None = None
        try:
            await asyncio.wait_for(manager.upload_semaphore.acquire(), timeout=1)
        except TimeoutError as exc:
            await security.audit(
                actor,
                device_id,
                "apps.install",
                request.state.request_id,
                "allowed",
                "rejected",
                error="upload_capacity_exceeded",
            )
            raise HTTPException(429, "Upload capacity exceeded") from exc
        try:
            if (
                request.headers.get("content-type", "").split(";")[0]
                != "application/vnd.android.package-archive"
            ):
                raise ValueError("APK content type required")
            with tempfile.NamedTemporaryFile(
                dir=manager.artifacts, suffix=".apk", delete=False
            ) as file:
                path = Path(file.name)
                size = 0
                async with asyncio.timeout(120):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > manager.settings.apk_max_bytes:
                            raise ValueError("APK upload too large")
                        file.write(chunk)
            validate_apk(path, manager.settings.apk_max_bytes)
            op = await manager.submit(device_id, "apps.install", actor, apk=path)
            path = None
            await security.audit(actor, device_id, "apps.install", op["id"], "allowed", "queued")
            return op
        except (ValueError, DeviceNotFound, TimeoutError) as exc:
            await security.audit(
                actor,
                device_id,
                "apps.install",
                request.state.request_id,
                "allowed",
                "rejected",
                error="apk_upload_rejected",
            )
            raise HTTPException(
                408 if isinstance(exc, TimeoutError) else (413 if "too large" in str(exc) else 400),
                "Upload timeout" if isinstance(exc, TimeoutError) else str(exc),
            ) from exc
        finally:
            manager.upload_semaphore.release()
            if path:
                path.unlink(missing_ok=True)

    @api.get("/operations/{operation_id}/screenshot")
    async def screenshot(operation_id: str, request: Request) -> FileResponse:
        await security.authorize(request, "control.screen")
        op = get(operation_id)
        manager.prune()
        path = manager.artifacts / (op["id"] + ".png")
        if op["action"] != "screenshot" or op["state"] != "succeeded" or not path.is_file():
            raise HTTPException(404, "Screenshot unavailable or expired")
        return FileResponse(
            path,
            media_type="image/png",
            filename="screenshot.png",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return api
