"""Permission-enforced file manager API."""

import asyncio
import posixpath
import shutil
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.background import BackgroundTask

from android_fleet.devices.models import Device, DeviceState
from android_fleet.devices.registry import DeviceNotFound
from android_fleet.files.backend import FileBackend
from android_fleet.files.paths import (
    FileError,
    ensure_writable,
    has_root,
    locations,
    normalize,
    validate_name,
)
from android_fleet.files.uploads import Upload, UploadManager

STATUS = {
    "not_found": 404,
    "exists": 409,
    "conflict": 409,
    "offline": 409,
    "busy": 429,
    "too_large": 413,
    "insufficient_storage": 507,
    "timeout": 504,
    "device_error": 502,
    "read_only": 422,
    "permission_denied": 422,
}


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)


class RenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)
    name: str = Field(max_length=255)


class DeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)
    confirmed: StrictBool = False


class CommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str = Field(max_length=4096)
    overwrite: StrictBool = False


def http_error(exc: FileError) -> HTTPException:
    return HTTPException(STATUS.get(exc.code, 400), exc.message)


def router(
    backend: FileBackend,
    uploads: UploadManager,
    fleet: Any,
    security: Any,
    *,
    download_max_bytes: int,
) -> APIRouter:
    api = APIRouter(prefix="/api/v1")
    downloads = uploads.root / "downloads"

    async def actor_for(request: Request, device_id: str, permission: str) -> Any:
        request.state.audit_action = permission
        actor = await security.authorize(request, permission)
        await security.authorize_device(actor, device_id, permission)
        return actor

    def online(device_id: str) -> Device:
        try:
            device: Device = fleet.get(device_id)
        except DeviceNotFound as exc:
            raise HTTPException(404, "Device not found") from exc
        if device.state != DeviceState.ONLINE:
            raise HTTPException(409, "The device is offline")
        return device

    async def audited(actor: Any, device_id: str, action: str, request: Request, work: Any) -> Any:
        try:
            result = await work
        except FileError as exc:
            await security.audit(
                actor,
                device_id,
                action,
                request.state.request_id,
                "allowed",
                "failed",
                error=exc.code,
            )
            raise http_error(exc) from exc
        await security.audit(
            actor, device_id, action, request.state.request_id, "allowed", "succeeded"
        )
        return result

    @api.get("/devices/{device_id}/files/locations")
    async def device_locations(device_id: str, request: Request) -> dict[str, Any]:
        await actor_for(request, device_id, "files.read")
        device = online(device_id)
        return {
            "root": has_root(device),
            "locations": [asdict(place) for place in locations(device)],
        }

    @api.get("/devices/{device_id}/files")
    async def list_files(
        device_id: str, request: Request, path: str = Query(max_length=4096)
    ) -> dict[str, Any]:
        await actor_for(request, device_id, "files.read")
        device = online(device_id)
        try:
            path = normalize(path)
            entries = await backend.listing(device, path)
            try:
                ensure_writable(device, path, allow_root=True)
                writable = True
            except FileError:
                writable = False
        except FileError as exc:
            raise http_error(exc) from exc
        return {
            "path": path,
            "writable": writable,
            "entries": [asdict(entry) for entry in entries],
        }

    @api.get("/devices/{device_id}/files/preview")
    async def preview(
        device_id: str, request: Request, path: str = Query(max_length=4096)
    ) -> dict[str, Any]:
        await actor_for(request, device_id, "files.read")
        try:
            return asdict(await backend.preview(online(device_id), path))
        except FileError as exc:
            raise http_error(exc) from exc

    @api.get("/devices/{device_id}/files/download")
    async def download(
        device_id: str, request: Request, path: str = Query(max_length=4096)
    ) -> FileResponse:
        actor = await actor_for(request, device_id, "files.read")
        device = online(device_id)
        await asyncio.to_thread(downloads.mkdir, 0o700, True, True)
        local = downloads / uuid.uuid4().hex
        try:
            free = (await asyncio.to_thread(shutil.disk_usage, downloads)).free
            limit = min(download_max_bytes, max(0, free - uploads.reserve_bytes))
            await audited(
                actor,
                device_id,
                "files.download",
                request,
                backend.download(device, path, local, limit),
            )
        except BaseException:
            local.unlink(missing_ok=True)
            raise
        return FileResponse(
            local,
            filename=posixpath.basename(normalize(path)) or "download",
            media_type="application/octet-stream",
            background=BackgroundTask(local.unlink, missing_ok=True),
        )

    @api.post("/devices/{device_id}/files/folders", status_code=201)
    async def create_folder(device_id: str, body: FolderInput, request: Request) -> dict[str, str]:
        actor = await actor_for(request, device_id, "files.write")
        device = online(device_id)
        try:
            path = ensure_writable(device, body.path)
            validate_name(posixpath.basename(path))
        except FileError as exc:
            raise http_error(exc) from exc
        await audited(actor, device_id, "files.mkdir", request, backend.mkdir(device, path))
        return {"path": path}

    @api.post("/devices/{device_id}/files/rename")
    async def rename(device_id: str, body: RenameInput, request: Request) -> dict[str, str]:
        actor = await actor_for(request, device_id, "files.write")
        device = online(device_id)
        try:
            path = ensure_writable(device, body.path)
            target = ensure_writable(
                device, posixpath.join(posixpath.dirname(path), validate_name(body.name))
            )
        except FileError as exc:
            raise http_error(exc) from exc
        await audited(
            actor, device_id, "files.rename", request, backend.rename(device, path, target)
        )
        return {"path": target}

    @api.post("/devices/{device_id}/files/delete")
    async def delete(device_id: str, body: DeleteInput, request: Request) -> dict[str, str]:
        actor = await actor_for(request, device_id, "files.write")
        device = online(device_id)
        if not body.confirmed:
            raise HTTPException(400, "Confirm the removal first")
        try:
            path = ensure_writable(device, body.path)
        except FileError as exc:
            raise http_error(exc) from exc
        await audited(actor, device_id, "files.delete", request, backend.delete(device, path))
        return {"status": "deleted"}

    @api.post("/devices/{device_id}/files/uploads", status_code=201)
    async def create_upload(device_id: str, request: Request) -> dict[str, Any]:
        actor = await actor_for(request, device_id, "files.write")
        online(device_id)
        try:
            upload = await uploads.create(device_id, actor)
        except FileError as exc:
            raise http_error(exc) from exc
        return upload.public() | {
            "max_bytes": uploads.max_bytes,
            "max_files": uploads.max_files,
        }

    async def owned(request: Request, upload_id: str) -> tuple[Any, Upload]:
        request.state.audit_action = "files.write"
        actor = await security.authorize(request, "files.write")
        try:
            upload = uploads.get(upload_id, actor.identity)
        except FileError as exc:
            raise http_error(exc) from exc
        await security.authorize_device(actor, upload.device_id, "files.write")
        return actor, upload

    @api.put("/files/uploads/{upload_id}/content")
    async def upload_content(
        upload_id: str, request: Request, path: str = Query(max_length=4096)
    ) -> dict[str, Any]:
        _, upload = await owned(request, upload_id)
        declared = request.headers.get("content-length")
        try:
            size = await uploads.receive(
                upload,
                path,
                request.stream(),
                int(declared) if declared and declared.isdigit() else None,
            )
        except FileError as exc:
            raise http_error(exc) from exc
        except TimeoutError as exc:
            raise HTTPException(408, "Upload timeout") from exc
        return {"path": path, "size": size, "files": len(upload.files), "bytes": upload.bytes}

    @api.post("/files/uploads/{upload_id}/commit", status_code=202)
    async def commit(upload_id: str, body: CommitInput, request: Request) -> dict[str, Any]:
        actor, upload = await owned(request, upload_id)
        try:
            await uploads.commit(upload, body.destination, overwrite=body.overwrite)
        except FileError as exc:
            await security.audit(
                actor,
                upload.device_id,
                "files.upload",
                request.state.request_id,
                "allowed",
                "rejected",
                error=exc.code,
            )
            raise http_error(exc) from exc
        await security.audit(
            actor, upload.device_id, "files.upload", upload.id, "allowed", "queued"
        )
        return upload.public()

    @api.get("/files/uploads/{upload_id}")
    async def upload_status(upload_id: str, request: Request) -> dict[str, Any]:
        _, upload = await owned(request, upload_id)
        return upload.public()

    @api.delete("/files/uploads/{upload_id}")
    async def cancel(upload_id: str, request: Request) -> dict[str, str]:
        _, upload = await owned(request, upload_id)
        await uploads.cancel(upload)
        return {"status": "cancelled"}

    return api
