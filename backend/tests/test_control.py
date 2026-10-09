import asyncio
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.control.manager import Manager, validate_apk, validate_package
from android_fleet.core.settings import Settings
from android_fleet.devices.models import ConnectionType, Device, DeviceState


class Fleet:
    def __init__(self) -> None:
        self.device = Device(
            "device", "pixel-stock", "Demo", DeviceState.ONLINE, ConnectionType.USB
        )

    def get(self, device_id: str) -> Device:
        return self.device


async def make_manager(tmp_path: Path, **kwargs: Any) -> Manager:
    manager = Manager(FakeAdbClient(), Fleet(), Settings(**kwargs), tmp_path / "operations.db")  # type: ignore[arg-type]
    await manager.initialize()
    return manager


async def wait(manager: Manager, op: dict[str, Any]) -> dict[str, Any]:
    await asyncio.gather(*list(manager.tasks.values()))
    return manager.get(op["id"])


@pytest.mark.parametrize("package", ["com.example.valid", "org.Example_123.app"])
def test_valid_package(package: str) -> None:
    assert validate_package(package) == package


@pytest.mark.parametrize(
    "package",
    ["", "../path", "com.foo;reboot", "-p", "com.foo bar", "com.foo\nbar", "android", "com..foo"],
)
def test_invalid_package(package: str) -> None:
    with pytest.raises(ValueError):
        validate_package(package)


@pytest.mark.parametrize(
    "entry,manifest",
    [
        ("AndroidManifest.xml", b"bad"),
        ("../evil", b"\x03\x00\x08\x00"),
        ("/evil", b"\x03\x00\x08\x00"),
    ],
)
def test_apk_rejected(tmp_path: Path, entry: str, manifest: bytes) -> None:
    path = tmp_path / "upload.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry, manifest)
    with pytest.raises(ValueError):
        validate_apk(path, 1024)


def test_apk_valid_and_oversize(tmp_path: Path) -> None:
    pool = struct.pack("<HHIIIIII", 1, 28, 36, 1, 0, 0, 32, 0) + b"\x00" * 8
    start = struct.pack("<HHI", 0x102, 16, 36) + b"\x00" * 28
    end = struct.pack("<HHI", 0x103, 16, 24) + b"\x00" * 16
    chunks = pool + start + end
    manifest = struct.pack("<HHI", 3, 8, len(chunks) + 8) + chunks
    path = tmp_path / "upload.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", manifest)
    validate_apk(path, 1024)
    with pytest.raises(ValueError):
        validate_apk(path, 2)


@pytest.mark.parametrize(
    "action",
    [
        "state",
        "properties",
        "apps.list",
        "apps.inspect",
        "screen.wake",
        "screen.lock",
        "screenshot",
        "apps.launch",
        "apps.stop",
    ],
)
async def test_supported_operations(tmp_path: Path, action: str) -> None:
    manager = await make_manager(tmp_path)
    actor = SimpleNamespace(identity="operator", role="operator")
    op = await manager.submit("device", action, actor, package="com.example.demo")
    assert op["state"] == "queued"
    final = await wait(manager, op)
    assert final["state"] == "succeeded"
    assert final["duration"] >= 0
    assert manager.history()["total"] == 1
    await manager.close()


async def test_offline_and_special_reboot(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    actor = SimpleNamespace(identity="admin", role="administrator")
    manager.fleet.get("device").state = DeviceState.OFFLINE
    op = await manager.submit("device", "apps.list", actor)
    assert (await wait(manager, op))["state"] == "failed"
    manager.fleet.get("device").state = DeviceState.ONLINE
    op = await manager.submit("device", "reboot.recovery", actor, confirmed=True)
    assert (await wait(manager, op))["state"] == "failed"
    assert not manager.client.calls  # type: ignore[attr-defined]
    await manager.close()


async def test_confirmation_and_validation(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    actor = SimpleNamespace(identity="admin", role="administrator")
    for action, kwargs in [
        ("reboot", {}),
        ("apps.uninstall", {"package": "com.example.demo"}),
        ("apps.stop", {"package": "com.foo;reboot"}),
        ("properties", {"property": "secret.key"}),
        ("shell", {}),
    ]:
        with pytest.raises(ValueError):
            await manager.submit("device", action, actor, **kwargs)
    assert manager.history()["total"] == 0
    await manager.close()


async def test_recovery_does_not_replay(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    actor = SimpleNamespace(identity="admin", role="administrator")
    op = await manager.submit("device", "reboot", actor, confirmed=True)
    task = manager.tasks.pop(op["id"])
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await manager.close()
    recovered = await make_manager(tmp_path)
    assert recovered.get(op["id"])["state"] == "failed"
    assert not recovered.client.calls  # type: ignore[attr-defined]
    await recovered.close()


async def test_timeouts_cancel_and_serialization(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path, operations_timeout_seconds=0.02)
    active = 0
    maximum = 0

    async def execute(*args: Any) -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.1)
        finally:
            active -= 1

    manager.execute = execute  # type: ignore[method-assign]
    actor = SimpleNamespace(identity="operator", role="operator")
    first = await manager.submit("device", "state", actor)
    second = await manager.submit("device", "state", actor)
    await asyncio.sleep(0)
    cancelled = await manager.cancel(second["id"])
    assert cancelled["state"] == "cancelled"
    assert (await wait(manager, first))["state"] == "timed_out"
    assert maximum == 1
    await manager.close()


async def test_queue_bound_and_temp_cleanup(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path, operations_max_queued=1)
    actor = SimpleNamespace(identity="admin", role="administrator")
    path = manager.artifacts / "test.apk"
    path.write_bytes(b"apk")
    op = await manager.submit("device", "apps.install", actor, apk=path)
    with pytest.raises(ValueError, match="queue"):
        await manager.submit("device", "state", actor)
    await wait(manager, op)
    assert not path.exists()
    await manager.close()


async def test_screenshot_retention(tmp_path: Path) -> None:
    import os

    manager = await make_manager(tmp_path)
    path = manager.artifacts / "expired.png"
    path.write_bytes(b"png")
    os.utime(path, (1, 1))
    manager.prune()
    assert not path.exists()
    await manager.close()


async def test_real_security_api_rejections_and_screenshot(tmp_path: Path) -> None:
    import hashlib
    import json

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from android_fleet.control.api import router
    from android_fleet.security import SecurityService

    credentials = json.dumps(
        [
            {
                "identity": role,
                "role": role,
                "token_hash": hashlib.sha256((role + "-secret").encode()).hexdigest(),
            }
            for role in ("viewer", "operator", "administrator")
        ]
    )
    settings = Settings(rbac_credentials=credentials)
    security = SecurityService(settings, tmp_path / "security.db")
    await security.initialize()
    manager = await make_manager(tmp_path)
    app = FastAPI()
    app.include_router(router(manager, security))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        admin = {"Authorization": "Bearer administrator-secret"}
        operator = {"Authorization": "Bearer operator-secret"}
        response = await client.post(
            "/api/v1/devices/device/operations",
            headers=operator,
            json={"action": "apps.stop", "package": "com.foo;reboot"},
        )
        assert response.status_code == 400
        response = await client.post(
            "/api/v1/devices/device/apk",
            headers={**admin, "Content-Type": "application/vnd.android.package-archive"},
            content=b"not an apk",
        )
        assert response.status_code == 400
        assert not list(manager.artifacts.glob("*.apk"))
        response = await client.post(
            "/api/v1/devices/device/operations",
            headers=admin,
            json={"action": "reboot", "confirmed": "true"},
        )
        assert response.status_code == 422
        response = await client.post(
            "/api/v1/devices/device/operations", headers=operator, json={"action": "screenshot"}
        )
        assert response.status_code == 202
        op = await wait(manager, response.json())
        url = f"/api/v1/operations/{op['id']}/screenshot"
        assert (await client.get(url)).status_code == 401
        assert (
            await client.get(url, headers={"Authorization": "Bearer viewer-secret"})
        ).status_code == 403
        image = await client.get(url, headers=operator)
        assert image.status_code == 200
        assert image.content.startswith(b"\x89PNG")
        assert image.headers["cache-control"] == "no-store"
        response = await client.post(
            "/api/v1/devices/device/operations",
            headers=operator,
            json={"action": "reboot", "confirmed": True},
        )
        assert response.status_code == 403
    audit = await security.history()
    assert any(item["outcome"] == "rejected" for item in audit["items"])
    await manager.close()
    await security.close()


async def test_global_concurrency(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path, operations_concurrency=2)
    active = maximum = 0
    barrier = asyncio.Event()

    async def execute(*args: Any) -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await barrier.wait()
        finally:
            active -= 1

    manager.execute = execute  # type: ignore[method-assign]
    actor = SimpleNamespace(identity="operator", role="operator")
    for device in ["a", "b", "c", "d"]:
        await manager.submit(device, "state", actor)
    await asyncio.sleep(0)
    assert active == 2
    barrier.set()
    await asyncio.gather(*list(manager.tasks.values()))
    assert maximum == 2
    await manager.close()


async def test_protected_system_package_not_uninstalled(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    actor = SimpleNamespace(identity="admin", role="administrator")
    op = await manager.submit(
        "device", "apps.uninstall", actor, package="com.android.settings", confirmed=True
    )
    assert (await wait(manager, op))["state"] == "failed"
    assert not any(argv[0] == "uninstall" for _, argv in manager.client.calls)  # type: ignore[attr-defined]
    await manager.close()


@pytest.mark.parametrize("image", [b"not png", b"\x89PNG\r\n\x1a\n" + b"x" * 2048])
async def test_invalid_or_oversized_capture_not_stored(tmp_path: Path, image: bytes) -> None:
    manager = await make_manager(tmp_path, screenshot_max_bytes=1024)

    async def screenshot(*args: Any, **kwargs: Any) -> bytes:
        return image

    manager.client.screenshot = screenshot  # type: ignore[method-assign]
    actor = SimpleNamespace(identity="operator", role="operator")
    op = await manager.submit("device", "screenshot", actor)
    assert (await wait(manager, op))["state"] == "failed"
    assert not list(manager.artifacts.glob("*.png"))
    await manager.close()
