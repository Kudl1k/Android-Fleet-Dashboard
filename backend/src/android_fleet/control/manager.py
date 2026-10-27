"""Persistent, bounded, non-root device operations."""

import asyncio
import json
import os
import re
import sqlite3
import struct
import time
import uuid
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from android_fleet.setup.service import DeviceSetup

from android_fleet.adb.base import AdbClient
from android_fleet.control.packages import (
    PackageCategory,
    classify,
    parse_diskstats,
    parse_packages,
    removable,
)
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.devices.service import FleetService
from android_fleet.security import ROLE_PERMISSIONS, Actor
from android_fleet.setup.catalog import SetupError

PERMISSIONS = {
    "setup.termux": "terminal:profile:manage",
    "setup.ssh": "terminal:profile:manage",
    **dict.fromkeys(("state", "properties", "apps.list", "apps.inspect"), "control.inspect"),
    **dict.fromkeys(("screen.wake", "screen.lock", "screenshot"), "control.screen"),
    "reboot": "control.reboot",
    "reboot.recovery": "control.reboot_special",
    "reboot.bootloader": "control.reboot_special",
    **{f"apps.{v}": f"apps.{v}" for v in ("launch", "stop", "install", "uninstall")},
    "apps.restore": "apps.install",
    "apps.cleanup": "apps.uninstall",
}
PROPERTIES = (
    "ro.product.manufacturer",
    "ro.product.model",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.product.cpu.abi",
    "ro.boot.bootloader",
)
DESTRUCTIVE = {
    "setup.termux",
    "setup.ssh",
    "reboot",
    "reboot.recovery",
    "reboot.bootloader",
    "apps.uninstall",
    "apps.cleanup",
}
NONCANCELLABLE = DESTRUCTIVE | {"apps.install", "apps.restore", "apps.stop", "apps.launch"}
CLEANUP_TIMEOUT_SECONDS = 300


def validate_package(package: str | None) -> str:
    if (
        package is None
        or len(package) > 255
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package)
    ):
        raise ValueError("Invalid Android package identifier")
    return package


def validate_apk(path: Path, limit: int) -> None:
    if path.stat().st_size > limit:
        raise ValueError("APK upload too large")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len({entry.filename for entry in entries}) != len(entries):
                raise ValueError("Duplicate APK archive entries")
            if len(entries) > 10000 or sum(v.file_size for v in entries) > limit * 8:
                raise ValueError("APK archive exceeds limits")
            for entry in entries:
                if (
                    entry.filename.startswith("/")
                    or ".." in Path(entry.filename).parts
                    or "\\" in entry.filename
                ):
                    raise ValueError("Unsafe APK archive path")
            manifest = archive.getinfo("AndroidManifest.xml")
            if manifest.file_size > 2 * 1024 * 1024:
                raise ValueError("APK manifest exceeds limit")
            data = archive.read(manifest)
            validate_manifest(data)
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Malformed APK archive") from exc


def validate_manifest(data: bytes) -> None:
    if len(data) < 8 or data[:4] != b"\x03\x00\x08\x00":
        raise ValueError("Invalid binary manifest header")
    if struct.unpack_from("<I", data, 4)[0] != len(data):
        raise ValueError("Invalid manifest length")
    offset, pool, start, end = 8, False, False, False
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError("Truncated manifest chunk")
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        if header < 8 or size < header or offset + size > len(data):
            raise ValueError("Invalid manifest chunk bounds")
        if kind == 1:
            if header < 28:
                raise ValueError("Invalid manifest string pool")
            count, styles, flags, strings_start, styles_start = struct.unpack_from(
                "<IIIII", data, offset + 8
            )
            if (
                count < 1
                or count > 100000
                or header + 4 * (count + styles) > size
                or strings_start >= size
            ):
                raise ValueError("Invalid manifest string pool bounds")
            if styles_start and styles_start >= size:
                raise ValueError("Invalid manifest style bounds")
            pool = True
        elif kind == 0x102:
            if header < 16 or size < header + 20 or not pool:
                raise ValueError("Invalid manifest start element")
            start = True
        elif kind == 0x103:
            if header < 16 or size < header + 8 or not start:
                raise ValueError("Invalid manifest end element")
            end = True
        offset += size
    if not (pool and start and end):
        raise ValueError("Manifest requires string pool and XML elements")


class Manager:
    def __init__(
        self,
        client: AdbClient,
        fleet: FleetService,
        settings: Settings,
        path: Path,
        setup: "DeviceSetup | None" = None,
    ) -> None:
        self.client, self.fleet, self.settings = client, fleet, settings
        self.setup = setup
        self.path = Path(path)
        self.artifacts = self.path.parent / "control-artifacts"
        self.db: sqlite3.Connection | None = None
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.semaphore = asyncio.Semaphore(settings.operations_concurrency)
        self.upload_semaphore = asyncio.Semaphore(2)
        self.security: Any = None
        self.maintenance: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.artifacts, 0o700)
        self.db = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("Unsupported operation database schema")
        self.db.execute("PRAGMA user_version=1")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS control_operations "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        for operation in self.history(limit=1000000)["items"]:
            if operation["state"] in {"queued", "running"}:
                operation.update(
                    state="failed",
                    finished_at=time.time(),
                    error="Interrupted by backend restart; action was not replayed",
                    cancellable=False,
                )
                self.save(operation)
                if self.security:
                    recovered_actor = Actor(
                        operation["actor"],
                        operation["role"],
                        ROLE_PERMISSIONS.get(operation["role"], frozenset()),
                    )
                    await self.security.audit(
                        recovered_actor,
                        operation["device_id"],
                        operation["action"],
                        operation["id"],
                        "allowed",
                        "failed",
                        error="backend_restart",
                    )
        for path in self.artifacts.glob("*.apk"):
            path.unlink(missing_ok=True)
        self.prune()

    async def start(self) -> None:
        async def cleanup() -> None:
            while True:
                await asyncio.sleep(60)
                self.prune()

        self.maintenance = asyncio.create_task(cleanup())

    def prune(self) -> None:
        cutoff = time.time() - self.settings.screenshot_retention_seconds
        for path in self.artifacts.glob("*.png"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        if self.maintenance:
            tasks.append(self.maintenance)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for path in self.artifacts.glob("*.apk"):
            path.unlink(missing_ok=True)
        if self.db:
            self.db.close()
            self.db = None

    def save(self, op: dict[str, Any]) -> None:
        assert self.db is not None
        self.db.execute(
            "INSERT OR REPLACE INTO control_operations VALUES (?,?)", (op["id"], json.dumps(op))
        )
        self.db.commit()

    def get(self, operation_id: str) -> dict[str, Any]:
        assert self.db is not None
        row = self.db.execute(
            "SELECT data FROM control_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return json.loads(row[0])  # type: ignore[no-any-return]

    def history(
        self,
        *,
        device_id: str | None = None,
        action: str | None = None,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        assert self.db is not None
        clauses, values = [], []
        for field, value in [("device_id", device_id), ("action", action), ("state", state)]:
            if value:
                clauses.append(f"json_extract(data, '$.{field}')=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = self.db.execute(
            "SELECT count(*) FROM control_operations" + where, values
        ).fetchone()[0]
        rows = self.db.execute(
            "SELECT data FROM control_operations"
            + where
            + " ORDER BY json_extract(data, '$.created_at') DESC LIMIT ? OFFSET ?",
            [*values, limit, offset],
        )
        return {"items": [json.loads(row[0]) for row in rows], "total": total}

    async def submit(
        self,
        device_id: str,
        action: str,
        actor: Any,
        *,
        package: str | None = None,
        property: str | None = None,
        confirmed: bool = False,
        apk: Path | None = None,
    ) -> dict[str, Any]:
        if action not in PERMISSIONS:
            raise ValueError("Unsupported operation")
        if action in DESTRUCTIVE and not confirmed:
            raise ValueError("Explicit confirmation is required")
        if action.startswith("apps.") and action not in {
            "apps.list",
            "apps.install",
            "apps.cleanup",
        }:
            package = validate_package(package)
        if property and property not in PROPERTIES:
            raise ValueError("Property is not allowlisted")
        self.fleet.get(device_id)
        if (
            sum(self.history(state=v)["total"] for v in ("running", "queued"))
            >= self.settings.operations_max_queued
        ):
            raise ValueError("Operation queue is full")
        op = dict(
            id=str(uuid.uuid4()),
            device_id=device_id,
            action=action,
            actor=actor.identity,
            role=actor.role,
            state="queued",
            created_at=time.time(),
            started_at=None,
            finished_at=None,
            duration=0.0,
            result=None,
            error=None,
            cancellable=action not in NONCANCELLABLE,
        )
        self.save(op)
        self.tasks[op["id"]] = asyncio.create_task(self._run(op, actor, package, property, apk))
        return op

    async def cancel(self, operation_id: str) -> dict[str, Any]:
        op = self.get(operation_id)
        if op["state"] not in {"queued", "running"} or not op["cancellable"]:
            raise ValueError("Operation cannot be safely cancelled")
        task = self.tasks.get(operation_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.tasks.pop(operation_id, None)
        op = self.get(operation_id)
        if op["state"] == "queued":
            op.update(state="cancelled", finished_at=time.time(), cancellable=False)
            self.save(op)
        return op

    async def _run(
        self,
        op: dict[str, Any],
        actor: Any,
        package: str | None,
        property: str | None,
        apk: Path | None,
    ) -> None:
        started: float | None = None
        try:
            async with self.locks.setdefault(op["device_id"], asyncio.Lock()), self.semaphore:
                started = time.monotonic()
                op.update(state="running", started_at=time.time())
                self.save(op)
                async with asyncio.timeout(
                    self.settings.operations_timeouts.get(
                        op["action"],
                        600
                        if op["action"].startswith("setup.")
                        else CLEANUP_TIMEOUT_SECONDS
                        if op["action"] == "apps.cleanup"
                        else self.settings.operations_timeout_seconds,
                    )
                ):
                    if op["action"].startswith("setup."):
                        if self.setup is None:
                            raise SetupError("Device setup is unavailable")
                        if self.security:
                            await self.security.authorize_device(
                                actor, op["device_id"], "apps.install"
                            )
                            await self.security.authorize_device(
                                actor, op["device_id"], "terminal:profile:manage"
                            )

                        def progress(stage: str) -> None:
                            op["result"] = {"stage": stage}
                            self.save(op)

                        op["result"] = await self.setup.run(op["device_id"], op["action"], progress)
                    else:
                        op["result"] = await self.execute(op, package, property, apk)
                op["state"] = "succeeded"
        except asyncio.CancelledError:
            op.update(
                state="cancelled",
                error="Execution interrupted; device effects may already have occurred",
            )
        except TimeoutError:
            op.update(
                state="timed_out",
                error="Execution timeout; device effects may already have occurred",
            )
        except SetupError as error:
            op.update(state="failed", error=str(error))
        except Exception as error:
            safe_errors = {
                "Device is offline": "Device is offline; reconnect before retrying",
                "Protected package": "Protected/system packages cannot be uninstalled",
                "Package is not removed": "Only removed preinstalled apps can be restored",
                (
                    "Special reboot capability is not verified for this device"
                ): "Recovery/bootloader support is unverified for this device",
                "Application has no launchable activity": "Application has no launchable activity",
                "Android rejected operation": "Android rejected or does not support this operation",
                "Screenshot unsupported or unavailable": "Screenshot unsupported or unavailable",
                "Output exceeds limit": "Device output exceeded the size limit",
                "ADB output limit exceeded": "Device output exceeded the size limit",
                "Screenshot size limit exceeded": "Screenshot exceeded the size limit",
            }
            op.update(
                state="failed",
                error=safe_errors.get(str(error), "Device unavailable or operation unsupported"),
            )
        finally:
            if apk:
                await asyncio.to_thread(apk.unlink, missing_ok=True)
            op.update(
                finished_at=time.time(),
                duration=round(time.monotonic() - started, 3) if started is not None else 0.0,
                cancellable=False,
            )
            self.save(op)
            self.tasks.pop(op["id"], None)
            if self.security:
                await self.security.audit(
                    actor,
                    op["device_id"],
                    op["action"],
                    op["id"],
                    "allowed",
                    op["state"],
                    op["duration"],
                    "operation_" + op["state"] if op["error"] else None,
                )

    async def execute(
        self, op: dict[str, Any], package: str | None, property: str | None, apk: Path | None
    ) -> Any:
        device = self.fleet.get(op["device_id"])
        action = op["action"]
        if action == "state":
            return {"state": device.state}
        if device.state != DeviceState.ONLINE:
            raise RuntimeError("Device is offline")
        serial = device.serial
        timeout = self.settings.operations_timeouts.get(
            action, self.settings.operations_timeout_seconds
        )

        async def shell(argv: tuple[str, ...]) -> str:
            result = await self.client.shell(serial, argv, timeout=timeout)
            if result.timeout:
                raise TimeoutError
            if result.exit_code != 0:
                raise RuntimeError("Android rejected operation")
            if len(result.stdout.encode()) > 1024 * 1024:
                raise RuntimeError("Output exceeds limit")
            return result.stdout

        if action == "properties":
            return {
                key: (await shell(("getprop", key))).strip()[:1024]
                for key in ((property,) if property else PROPERTIES)
            }
        if action == "screenshot":
            image = await self.client.screenshot(
                serial, timeout=timeout, max_bytes=self.settings.screenshot_max_bytes
            )
            if len(image) > self.settings.screenshot_max_bytes or not image.startswith(
                b"\x89PNG\r\n\x1a\n"
            ):
                raise RuntimeError("Invalid or oversized screenshot")
            path = self.artifacts / (op["id"] + ".png")
            path.write_bytes(image)
            os.chmod(path, 0o600)
            return {
                "screenshot_url": f"/api/v1/operations/{op['id']}/screenshot",
                "bytes": len(image),
            }

        async def inventory() -> tuple[set[str], set[str], set[str]]:
            installed = parse_packages(await shell(("pm", "list", "packages")))
            system = parse_packages(await shell(("pm", "list", "packages", "-s")))
            known = parse_packages(await shell(("pm", "list", "packages", "-u")))
            return installed, system, known - installed

        async def sizes() -> dict[str, int]:
            # Sizes are informative only; a missing or failing diskstats keeps the list usable.
            try:
                return parse_diskstats(await shell(("dumpsys", "diskstats")))
            except (RuntimeError, TimeoutError):
                return {}

        async def remove(name: str, system: bool) -> None:
            if system:
                output = await shell(("pm", "uninstall", "--user", "0", name))
                if "Success" not in output:
                    raise RuntimeError("Android rejected operation")
                return
            result = await self.client.command(serial, ("uninstall", name), timeout=timeout)
            if result.timeout:
                raise TimeoutError
            if result.exit_code != 0 or "Success" not in result.stdout:
                raise RuntimeError("Android rejected operation")

        if action == "apps.list":
            installed, system, removed = await inventory()
            used = await sizes()
            return {
                "packages": sorted(installed),
                "apps": [
                    {
                        "package": name,
                        "system": name in system,
                        "category": classify(name, name in system),
                        "size_bytes": used.get(name),
                    }
                    for name in sorted(installed)
                ],
                "removed": sorted(removed),
            }
        if action == "apps.inspect":
            output = await shell(("dumpsys", "package", str(package)))
            return {
                "package": package,
                "metadata": [
                    line.strip()[:512]
                    for line in output.splitlines()
                    if any(
                        key in line
                        for key in (
                            "versionName=",
                            "versionCode=",
                            "firstInstallTime=",
                            "lastUpdateTime=",
                        )
                    )
                ][:20],
            }
        if action == "apps.uninstall":
            system = parse_packages(await shell(("pm", "list", "packages", "-s")))
            if not removable(classify(str(package), str(package) in system)):
                raise RuntimeError("Protected package")
            await remove(str(package), str(package) in system)
            return {"acknowledged": True, "package": package}
        if action == "apps.restore":
            _, _, removed = await inventory()
            if package not in removed:
                raise RuntimeError("Package is not removed")
            output = await shell(("pm", "install-existing", str(package)))
            if "installed" not in output:
                raise RuntimeError("Android rejected operation")
            return {"acknowledged": True, "package": package}
        if action == "apps.cleanup":
            installed, system, _ = await inventory()
            used = await sizes()
            targets = sorted(
                name
                for name in installed
                if classify(name, name in system) is PackageCategory.REMOVABLE
            )
            done: list[str] = []
            failed: list[str] = []
            for name in targets:
                try:
                    await remove(name, name in system)
                    done.append(name)
                except RuntimeError:
                    failed.append(name)
            return {
                "removed": done,
                "failed": failed,
                "freed_bytes_estimate": sum(used.get(name, 0) for name in done),
            }
        if action == "apps.install":
            assert apk is not None
            result = await self.client.command(serial, ("install", str(apk)), timeout=timeout)
        elif action.startswith("reboot"):
            if action != "reboot":
                # Vendor recovery/bootloader support cannot be safely inferred on stock devices.
                raise RuntimeError("Special reboot capability is not verified for this device")
            result = await self.client.command(serial, ("reboot",), timeout=timeout)
        else:
            commands = {
                "screen.wake": ("input", "keyevent", "224"),
                "screen.lock": ("input", "keyevent", "223"),
                "apps.launch": (
                    "monkey",
                    "-p",
                    str(package),
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ),
                "apps.stop": ("am", "force-stop", str(package)),
            }
            output = await shell(commands[action])
            if action == "apps.launch" and any(
                value in output for value in ("No activities found", "monkey aborted", "Error:")
            ):
                raise RuntimeError("Application has no launchable activity")
            return {
                "acknowledged": True,
                **(
                    {"effect": "screen_sleep; secure keyguard is controlled by Android policy"}
                    if action == "screen.lock"
                    else {}
                ),
            }
        if result.timeout:
            raise TimeoutError
        if result.exit_code != 0 or (action.startswith("apps.") and "Success" not in result.stdout):
            raise RuntimeError("Android rejected operation")
        return {"acknowledged": True}
