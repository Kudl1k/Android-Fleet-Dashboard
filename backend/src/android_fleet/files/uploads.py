"""Staged uploads: files are collected on the manager, then copied in one transfer.

A folder such as a benchmark with a model and hundreds of images becomes one
``adb push`` and one copy on the device instead of a round trip per file.
"""

import asyncio
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from android_fleet.devices.models import Device, DeviceState
from android_fleet.devices.registry import DeviceNotFound
from android_fleet.files.backend import FileBackend
from android_fleet.files.paths import FileError, ensure_writable, validate_relative

UPLOAD_TTL_SECONDS = 3600
DISK_CHECK_BYTES = 8 * 1024 * 1024


@dataclass
class Upload:
    id: str
    device_id: str
    actor: Any
    root: Path
    created_at: float = field(default_factory=time.time)
    files: dict[str, int] = field(default_factory=dict)
    bytes: int = 0
    state: str = "receiving"
    destination: str | None = None
    error: str | None = None
    finished_at: float | None = None
    receiving: int = 0
    task: asyncio.Task[None] | None = None

    @property
    def identity(self) -> str:
        return str(self.actor.identity)

    @property
    def tree(self) -> Path:
        return self.root / "tree"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "state": self.state,
            "files": len(self.files),
            "bytes": self.bytes,
            "destination": self.destination,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class UploadManager:
    def __init__(
        self,
        backend: FileBackend,
        device: Any,
        root: Path,
        *,
        max_bytes: int,
        max_files: int,
        reserve_bytes: int,
        on_finish: Callable[[Upload], Awaitable[None]] | None = None,
    ) -> None:
        self.on_finish = on_finish
        self.backend = backend
        self.device = device
        self.root = root
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.reserve_bytes = reserve_bytes
        self.uploads: dict[str, Upload] = {}

    async def initialize(self) -> None:
        def prepare() -> None:
            # Uploads never survive a restart; leftovers are only wasted disk.
            shutil.rmtree(self.root, ignore_errors=True)
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

        await asyncio.to_thread(prepare)

    async def close(self) -> None:
        tasks = [u.task for u in self.uploads.values() if u.task and not u.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _online(self, device_id: str) -> Device:
        try:
            device: Device = self.device(device_id)
        except DeviceNotFound as exc:
            raise FileError("not_found", "Device not found") from exc
        if device.state != DeviceState.ONLINE:
            raise FileError("offline", "The device is offline")
        return device

    async def _expire(self) -> None:
        now = time.time()
        for upload in list(self.uploads.values()):
            busy = upload.state == "transferring" or upload.receiving
            if not busy and now - upload.created_at > UPLOAD_TTL_SECONDS:
                await self._discard(upload)

    async def _discard(self, upload: Upload) -> None:
        self.uploads.pop(upload.id, None)
        await asyncio.to_thread(shutil.rmtree, upload.root, True)

    async def create(self, device_id: str, actor: Any) -> Upload:
        await self._expire()
        self._online(device_id)
        active = [u for u in self.uploads.values() if u.state in {"receiving", "transferring"}]
        if len(active) >= 8 or sum(u.identity == actor.identity for u in active) >= 4:
            raise FileError("busy", "Too many uploads in progress; finish or cancel one first")
        upload = Upload(uuid.uuid4().hex, device_id, actor, self.root / uuid.uuid4().hex)
        await asyncio.to_thread(upload.tree.mkdir, 0o700, True)
        self.uploads[upload.id] = upload
        return upload

    def get(self, upload_id: str, identity: str) -> Upload:
        upload = self.uploads.get(upload_id)
        if upload is None or upload.identity != identity:
            raise FileError("not_found", "This upload does not exist or has expired")
        return upload

    def _target(self, upload: Upload, relative: str) -> tuple[str, Path]:
        parts = validate_relative(relative)
        key = "/".join(parts)
        if key in upload.files:
            raise FileError("exists", f"{key} was already uploaded")
        for name in upload.files:
            # A path cannot be a file and a folder at the same time.
            if name.startswith(key + "/") or key.startswith(name + "/"):
                raise FileError("exists", f"{key} conflicts with {name}")
        return key, upload.tree.joinpath(*parts)

    async def receive(
        self,
        upload: Upload,
        relative: str,
        chunks: AsyncIterator[bytes],
        declared: int | None,
    ) -> int:
        if upload.state != "receiving":
            raise FileError("conflict", "This upload no longer accepts files")
        if len(upload.files) >= self.max_files:
            raise FileError("too_large", f"An upload can hold at most {self.max_files} files")
        key, target = self._target(upload, relative)
        if declared is not None and upload.bytes + declared > self.max_bytes:
            raise FileError("too_large", self._limit_message())
        await self._check_disk(declared or 0)
        upload.receiving += 1
        partial = target.with_name(target.name + f".part-{uuid.uuid4().hex}")
        size = 0
        try:
            await asyncio.to_thread(target.parent.mkdir, 0o700, True, True)
            # Reserve the name at once so a parallel upload of the same path is refused.
            upload.files[key] = 0
            with partial.open("wb") as file:
                checked = 0
                async with asyncio.timeout(900):
                    async for chunk in chunks:
                        size += len(chunk)
                        if upload.bytes + size > self.max_bytes:
                            raise FileError("too_large", self._limit_message())
                        if size - checked >= DISK_CHECK_BYTES:
                            checked = size
                            await self._check_disk(0)
                        await asyncio.to_thread(file.write, chunk)
            await asyncio.to_thread(partial.replace, target)
        except BaseException:
            upload.files.pop(key, None)
            partial.unlink(missing_ok=True)
            raise
        finally:
            upload.receiving -= 1
        upload.files[key] = size
        upload.bytes += size
        return size

    def _limit_message(self) -> str:
        return f"An upload can hold at most {self.max_bytes // 1048576} MiB"

    async def _check_disk(self, incoming: int) -> None:
        free = (await asyncio.to_thread(shutil.disk_usage, self.root)).free
        if free - incoming < self.reserve_bytes:
            raise FileError("insufficient_storage", "The manager is running out of disk space")

    async def commit(self, upload: Upload, destination: str, *, overwrite: bool) -> Upload:
        if upload.state != "receiving" or upload.receiving:
            raise FileError("conflict", "Wait until every file has finished uploading")
        if not upload.files:
            raise FileError("empty", "Add at least one file before uploading")
        device = self._online(upload.device_id)
        destination = ensure_writable(device, destination, allow_root=True)
        names = sorted({name.split("/", 1)[0] for name in upload.files})
        if not overwrite:
            existing = await self.backend.conflicts(device, destination, names)
            if existing:
                shown = ", ".join(existing[:5]) + (" …" if len(existing) > 5 else "")
                raise FileError("exists", f"Already in the destination: {shown}")
        upload.state = "transferring"
        upload.destination = destination
        # Roughly 1 MB/s over Wi-Fi ADB plus a fixed allowance for the copy on the device.
        timeout = min(3600.0, 120 + upload.bytes / 1_000_000)
        upload.task = asyncio.create_task(
            self._transfer(upload, device, destination, names, overwrite, timeout)
        )
        return upload

    async def _transfer(
        self,
        upload: Upload,
        device: Device,
        destination: str,
        names: list[str],
        overwrite: bool,
        timeout: float,
    ) -> None:
        try:
            await self.backend.install(
                device, upload.tree, destination, names, overwrite=overwrite, timeout=timeout
            )
            upload.state = "completed"
        except FileError as exc:
            upload.state, upload.error = "failed", exc.message
        except asyncio.CancelledError:
            upload.state, upload.error = "cancelled", "The transfer was cancelled"
            raise
        except Exception:
            upload.state, upload.error = "failed", "The transfer failed unexpectedly"
        finally:
            upload.finished_at = time.time()
            with suppress(OSError):
                await asyncio.to_thread(shutil.rmtree, upload.tree, True)
            if self.on_finish:
                with suppress(Exception):
                    await self.on_finish(upload)

    async def cancel(self, upload: Upload) -> None:
        if upload.task and not upload.task.done():
            upload.task.cancel()
            await asyncio.gather(upload.task, return_exceptions=True)
        elif upload.state == "receiving":
            upload.state, upload.finished_at = "cancelled", time.time()
        await self._discard(upload)
