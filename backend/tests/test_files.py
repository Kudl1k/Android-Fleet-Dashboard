"""Device file manager: path rules, ADB scripts, staged uploads and the API."""

import hashlib
import json
import re
import shlex
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import (
    ConnectionType,
    Device,
    DeviceCapability,
    DeviceState,
)
from android_fleet.execution.models import CommandResult
from android_fleet.files.backend import AdbFileBackend, parse_listing
from android_fleet.files.memory import MemoryFileBackend
from android_fleet.files.paths import (
    TERMUX_HOME,
    FileError,
    ensure_writable,
    normalize,
    validate_relative,
)
from android_fleet.files.uploads import UploadManager
from android_fleet.main import create_app

ROOTED = Device(
    "rooted",
    "pixel-rooted",
    "Pixel",
    DeviceState.ONLINE,
    ConnectionType.USB,
    capabilities={DeviceCapability.ROOT_SHELL},
)
STOCK = Device("stock", "pixel-stock", "Pixel", DeviceState.ONLINE, ConnectionType.USB)


# --------------------------------------------------------------------------- paths


@pytest.mark.parametrize("path", ["", "relative", "/a\nb", "/a\0b", "/" + "x" * 5000])
def test_normalize_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(FileError):
        normalize(path)


def test_normalize_collapses_dots() -> None:
    assert normalize("//sdcard/./a/../b/") == "/sdcard/b"


@pytest.mark.parametrize(
    "path",
    ["/sdcard/final", "/storage/emulated/0/x", "/data/local/tmp/run", TERMUX_HOME + "/a"],
)
def test_writable_inside_user_areas(path: str) -> None:
    assert ensure_writable(ROOTED, path) == path


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/system/bin/sh",
        "/data/data/com.termux/files/usr/bin",
        "/sdcard",  # the root itself can be listed and uploaded into, not removed
        "/sdcard/../system",
        "/data/local/tmp/fleet-files-" + "0" * 32,
    ],
)
def test_changes_outside_user_areas_are_refused(path: str) -> None:
    with pytest.raises(FileError):
        ensure_writable(ROOTED, path)


def test_termux_home_needs_root() -> None:
    with pytest.raises(FileError):
        ensure_writable(STOCK, TERMUX_HOME + "/script.py")
    assert ensure_writable(STOCK, "/sdcard", allow_root=True) == "/sdcard"


@pytest.mark.parametrize("path", ["../x", "a/../../x", "/abs", "a//b", "a/./b", "a\nb/c"])
def test_upload_paths_stay_relative(path: str) -> None:
    with pytest.raises(FileError):
        validate_relative(path)


def test_upload_paths_accept_windows_separators() -> None:
    assert validate_relative("final\\input\\a.jpg") == ("final", "input", "a.jpg")


# --------------------------------------------------------------------------- listing


def test_parse_listing_sorts_folders_first_and_keeps_odd_names() -> None:
    output = "\n".join(
        [
            "-rw-rw----|12|1700000000|u0_a206|u0_a206|run.py",
            "drwx------|4096|1700000001|u0_a206|u0_a206|final",
            "-rw-rw----|3|1700000002|root|root|a|b c.txt",
            "lrwxrwxrwx|7|1700000003|root|root|link",
            "garbage line",
            "-rw-rw----|notanumber|1|root|root|bad",
            "drwx------|4096|1|root|root|.",
        ]
    )
    entries = parse_listing("/data/home", output)
    assert [(e.name, e.kind) for e in entries] == [
        ("final", "directory"),
        ("a|b c.txt", "file"),
        ("link", "symlink"),
        ("run.py", "file"),
    ]
    assert entries[0].path == "/data/home/final"
    assert entries[3].size == 12


# --------------------------------------------------------------------------- ADB scripts


class Recorder(FakeAdbClient):
    def __init__(self, results: list[CommandResult] | None = None) -> None:
        super().__init__()
        self.results = results or []
        self.scripts: list[tuple[str, ...]] = []
        self.pushes: list[tuple[Path, str]] = []
        self.pulls: list[tuple[str, Path]] = []
        self.push_error: Exception | None = None

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        self.scripts.append(argv)
        return self.results.pop(0) if self.results else CommandResult(exit_code=0)

    async def push_tree(self, serial: str, local: Path, remote: str, *, timeout: float) -> None:
        self.pushes.append((local, remote))
        if self.push_error:
            raise self.push_error

    async def pull(self, serial: str, remote: str, local: Path, *, timeout: float) -> None:
        self.pulls.append((remote, local))


async def test_listing_uses_root_only_when_observed() -> None:
    adb = Recorder([CommandResult(stdout="-rw-r--r--|1|1|a|a|x\n", exit_code=0)])
    entries = await AdbFileBackend(adb).listing(ROOTED, "/data/data")
    assert adb.scripts[0][:2] == ("su", "-c")
    assert [e.name for e in entries] == ["x"]
    await AdbFileBackend(adb).listing(STOCK, "/sdcard")
    assert adb.scripts[1][:2] == ("sh", "-c")


async def test_paths_are_quoted_for_the_device_shell() -> None:
    adb = Recorder()
    evil = "/sdcard/x'; reboot; echo '"
    await AdbFileBackend(adb).delete(STOCK, evil)
    script = adb.scripts[0][2]
    assert f"rm -rf -- {shlex.quote(evil)}" in script
    # The shell sees exactly one argument for the path.
    assert shlex.split(script.splitlines()[-1].split(" || ")[0]) == ["rm", "-rf", "--", evil]


@pytest.mark.parametrize(
    "code,expected",
    [(3, "not_found"), (4, "not_directory"), (5, "permission_denied"), (1, "device_error")],
)
async def test_listing_reports_device_conditions(code: int, expected: str) -> None:
    adb = Recorder([CommandResult(exit_code=code)])
    with pytest.raises(FileError) as error:
        await AdbFileBackend(adb).listing(STOCK, "/sdcard/missing")
    assert error.value.code == expected


async def test_timeouts_are_reported() -> None:
    adb = Recorder([CommandResult(timeout=True, exit_code=None)])
    with pytest.raises(FileError) as error:
        await AdbFileBackend(adb).listing(STOCK, "/sdcard")
    assert error.value.code == "timeout"


async def test_install_into_termux_home_restores_owner_and_label(tmp_path: Path) -> None:
    adb = Recorder()
    await AdbFileBackend(adb).install(
        ROOTED, tmp_path, TERMUX_HOME, ["final"], overwrite=False, timeout=60
    )
    local, staging = adb.pushes[0]
    assert local == tmp_path
    assert re.fullmatch(r"/data/local/tmp/fleet-files-[0-9a-f]{32}", staging)
    script = adb.scripts[0][2]
    assert adb.scripts[0][:2] == ("su", "-c")
    assert f"cp -R -- {staging}/final {TERMUX_HOME}/final" in script
    assert "chown -R" in script and "chcon -R" in script
    assert "exit 6" in script  # refuses to replace without overwrite
    assert adb.scripts[-1][2] == f"rm -rf -- {staging}"


async def test_install_into_shared_storage_skips_ownership(tmp_path: Path) -> None:
    adb = Recorder()
    await AdbFileBackend(adb).install(
        STOCK, tmp_path, "/sdcard/Download", ["a.txt"], overwrite=True, timeout=60
    )
    script = adb.scripts[0][2]
    assert adb.scripts[0][:2] == ("sh", "-c")
    assert "chown" not in script
    assert "rm -rf -- /sdcard/Download/a.txt" in script


async def test_failed_transfer_still_cleans_staging(tmp_path: Path) -> None:
    adb = Recorder()
    adb.push_error = RuntimeError("adb push failed")
    with pytest.raises(FileError) as error:
        await AdbFileBackend(adb).install(
            ROOTED, tmp_path, "/sdcard", ["a"], overwrite=False, timeout=60
        )
    assert error.value.code == "device_error"
    assert adb.scripts[-1][2].startswith("rm -rf -- /data/local/tmp/fleet-files-")


async def test_root_download_copies_through_staging(tmp_path: Path) -> None:
    adb = Recorder([CommandResult(stdout="42\n", exit_code=0)])
    await AdbFileBackend(adb).download(ROOTED, TERMUX_HOME + "/run.py", tmp_path / "f", 1000)
    remote, local = adb.pulls[0]
    assert remote.startswith("/data/local/tmp/fleet-files-") and remote.endswith("/file")
    assert local == tmp_path / "f"
    assert adb.scripts[-1][2].startswith("rm -rf -- /data/local/tmp/fleet-files-")


async def test_download_limit() -> None:
    adb = Recorder([CommandResult(stdout="5000\n", exit_code=0)])
    with pytest.raises(FileError) as error:
        await AdbFileBackend(adb).download(STOCK, "/sdcard/big", Path("unused"), 1000)
    assert error.value.code == "too_large"
    assert not adb.pulls


async def test_preview_detects_binary_and_truncation() -> None:
    adb = Recorder(
        [
            CommandResult(stdout="9\nprint(1)\n", exit_code=0),
            CommandResult(stdout="999999\n\x00\x01", exit_code=0),
        ]
    )
    backend = AdbFileBackend(adb)
    text = await backend.preview(STOCK, "/sdcard/a.py")
    assert (text.content, text.binary, text.truncated) == ("print(1)\n", False, False)
    binary = await backend.preview(STOCK, "/sdcard/model.bin")
    assert binary.binary and binary.truncated and binary.content == ""


# --------------------------------------------------------------------------- uploads


class Actor:
    def __init__(self, identity: str = "admin") -> None:
        self.identity = identity


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def make_uploads(
    tmp_path: Path, device: Device = ROOTED, **limits: int
) -> tuple[UploadManager, MemoryFileBackend]:
    backend = MemoryFileBackend()
    manager = UploadManager(
        backend,
        lambda _id: device,
        tmp_path / "staging",
        max_bytes=limits.get("max_bytes", 10_000),
        max_files=limits.get("max_files", 100),
        reserve_bytes=0,
    )
    await manager.initialize()
    return manager, backend


async def finish(manager: UploadManager) -> None:
    for upload in manager.uploads.values():
        if upload.task:
            await upload.task


async def test_folder_upload_lands_in_the_destination(tmp_path: Path) -> None:
    manager, backend = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor())
    await manager.receive(upload, "final/telemetry.py", chunks(b"print", b"(1)"), 8)
    await manager.receive(upload, "final/input/a.jpg", chunks(b"jpg"), None)
    await manager.commit(upload, TERMUX_HOME, overwrite=False)
    await finish(manager)
    assert upload.state == "completed"
    tree = backend.devices["rooted"]
    assert tree[TERMUX_HOME + "/final/telemetry.py"].data == b"print(1)"
    assert tree[TERMUX_HOME + "/final/input/a.jpg"].data == b"jpg"
    assert not upload.tree.exists()


async def test_existing_items_need_overwrite(tmp_path: Path) -> None:
    manager, backend = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor())
    await manager.receive(upload, "hello.py", chunks(b"new"), None)
    with pytest.raises(FileError) as error:
        await manager.commit(upload, TERMUX_HOME, overwrite=False)
    assert error.value.code == "exists" and "hello.py" in error.value.message
    assert upload.state == "receiving"
    await manager.commit(upload, TERMUX_HOME, overwrite=True)
    await finish(manager)
    assert backend.devices["rooted"][TERMUX_HOME + "/hello.py"].data == b"new"


@pytest.mark.parametrize("second", ["a.txt", "a.txt/b", "dir"])
async def test_upload_paths_cannot_collide(tmp_path: Path, second: str) -> None:
    manager, _ = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor())
    await manager.receive(upload, "a.txt", chunks(b"1"), None)
    await manager.receive(upload, "dir/x", chunks(b"1"), None)
    with pytest.raises(FileError):
        await manager.receive(upload, second, chunks(b"2"), None)


async def test_upload_limits(tmp_path: Path) -> None:
    manager, _ = await make_uploads(tmp_path, max_bytes=10, max_files=2)
    upload = await manager.create("rooted", Actor())
    with pytest.raises(FileError):
        await manager.receive(upload, "declared", chunks(b""), 11)
    with pytest.raises(FileError):
        await manager.receive(upload, "streamed", chunks(b"123456", b"78901"), None)
    assert upload.files == {} and upload.bytes == 0
    assert not any(upload.tree.rglob("*.part-*"))
    await manager.receive(upload, "a", chunks(b"1"), None)
    await manager.receive(upload, "b", chunks(b"1"), None)
    with pytest.raises(FileError):
        await manager.receive(upload, "c", chunks(b"1"), None)


async def test_uploads_belong_to_their_creator(tmp_path: Path) -> None:
    manager, _ = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor("alice"))
    with pytest.raises(FileError):
        manager.get(upload.id, "bob")
    assert manager.get(upload.id, "alice") is upload


async def test_upload_refuses_system_destination(tmp_path: Path) -> None:
    manager, _ = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor())
    await manager.receive(upload, "a", chunks(b"1"), None)
    with pytest.raises(FileError) as error:
        await manager.commit(upload, "/system/bin", overwrite=True)
    assert error.value.code == "read_only"


async def test_offline_device_cannot_receive_uploads(tmp_path: Path) -> None:
    offline = Device("off", "x", "x", DeviceState.OFFLINE)
    manager, _ = await make_uploads(tmp_path, device=offline)
    with pytest.raises(FileError) as error:
        await manager.create("off", Actor())
    assert error.value.code == "offline"


async def test_cancel_discards_staged_files(tmp_path: Path) -> None:
    manager, _ = await make_uploads(tmp_path)
    upload = await manager.create("rooted", Actor())
    await manager.receive(upload, "a", chunks(b"1"), None)
    await manager.cancel(upload)
    assert upload.id not in manager.uploads
    assert not upload.root.exists()


async def test_disk_reserve_protects_the_manager(tmp_path: Path) -> None:
    manager, _ = await make_uploads(tmp_path)
    manager.reserve_bytes = 1 << 62
    upload = await manager.create("rooted", Actor())
    with pytest.raises(FileError) as error:
        await manager.receive(upload, "a", chunks(b"1"), None)
    assert error.value.code == "insufficient_storage"


# --------------------------------------------------------------------------- API


def credentials(*roles: str) -> str:
    return json.dumps(
        [
            {
                "identity": role,
                "role": role,
                "token_hash": hashlib.sha256(role.encode()).hexdigest(),
            }
            for role in roles
        ]
    )


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    settings = Settings(rbac_credentials=credentials("administrator", "operator", "viewer"))
    app = create_app(FakeAdbClient(), settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            yield client


def auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}


async def test_only_administrators_use_files(api: AsyncClient) -> None:
    for role in ("viewer", "operator"):
        response = await api.get(
            "/api/v1/devices/pixel-rooted/files?path=/sdcard", headers=auth(role)
        )
        assert response.status_code == 403
    response = await api.get(
        "/api/v1/devices/pixel-rooted/files?path=/sdcard", headers=auth("administrator")
    )
    assert response.status_code == 200
    assert response.json()["writable"] is True


async def test_locations_follow_root_access(api: AsyncClient) -> None:
    rooted = await api.get(
        "/api/v1/devices/pixel-rooted/files/locations", headers=auth("administrator")
    )
    stock = await api.get(
        "/api/v1/devices/pixel-stock/files/locations", headers=auth("administrator")
    )
    assert TERMUX_HOME in [p["path"] for p in rooted.json()["locations"]]
    assert TERMUX_HOME not in [p["path"] for p in stock.json()["locations"]]


async def test_upload_preview_download_rename_delete(api: AsyncClient) -> None:
    h = auth("administrator")
    base = "/api/v1/devices/pixel-rooted/files"
    created = await api.post(f"{base}/uploads", headers=h)
    assert created.status_code == 201
    upload = created.json()["id"]
    put = await api.put(
        f"/api/v1/files/uploads/{upload}/content?path=final/run.py",
        content=b"print('benchmark')\n",
        headers=h,
    )
    assert put.status_code == 200 and put.json()["bytes"] == 19
    traversal = await api.put(
        f"/api/v1/files/uploads/{upload}/content?path=../escape", content=b"x", headers=h
    )
    assert traversal.status_code == 400
    commit = await api.post(
        f"/api/v1/files/uploads/{upload}/commit",
        json={"destination": TERMUX_HOME, "overwrite": False},
        headers=h,
    )
    assert commit.status_code == 202
    status: dict[str, Any] = {}
    for _ in range(50):
        status = (await api.get(f"/api/v1/files/uploads/{upload}", headers=h)).json()
        if status["state"] != "transferring":
            break
    assert status["state"] == "completed"

    listing = await api.get(f"{base}?path={TERMUX_HOME}/final", headers=h)
    assert [e["name"] for e in listing.json()["entries"]] == ["run.py"]
    preview = await api.get(f"{base}/preview?path={TERMUX_HOME}/final/run.py", headers=h)
    assert preview.json()["content"] == "print('benchmark')\n"
    download = await api.get(f"{base}/download?path={TERMUX_HOME}/final/run.py", headers=h)
    assert download.status_code == 200 and download.content == b"print('benchmark')\n"
    assert "run.py" in download.headers["content-disposition"]

    renamed = await api.post(
        f"{base}/rename", json={"path": f"{TERMUX_HOME}/final", "name": "bench"}, headers=h
    )
    assert renamed.json()["path"] == f"{TERMUX_HOME}/bench"
    unconfirmed = await api.post(f"{base}/delete", json={"path": f"{TERMUX_HOME}/bench"}, headers=h)
    assert unconfirmed.status_code == 400
    deleted = await api.post(
        f"{base}/delete", json={"path": f"{TERMUX_HOME}/bench", "confirmed": True}, headers=h
    )
    assert deleted.status_code == 200
    gone = await api.get(f"{base}?path={TERMUX_HOME}/bench", headers=h)
    assert gone.status_code == 404


async def test_api_refuses_system_changes(api: AsyncClient) -> None:
    h = auth("administrator")
    base = "/api/v1/devices/pixel-rooted/files"
    for response in (
        await api.post(f"{base}/delete", json={"path": "/system", "confirmed": True}, headers=h),
        await api.post(f"{base}/folders", json={"path": "/data/app/x"}, headers=h),
        await api.post(f"{base}/rename", json={"path": "/sdcard", "name": "x"}, headers=h),
        await api.post(
            f"{base}/rename", json={"path": "/sdcard/Download", "name": "../x"}, headers=h
        ),
    ):
        assert response.status_code in {400, 422}, response.text


async def test_stock_phone_cannot_read_app_data(api: AsyncClient) -> None:
    response = await api.get(
        f"/api/v1/devices/pixel-stock/files?path={TERMUX_HOME}",
        headers=auth("administrator"),
    )
    assert response.status_code == 422


async def test_uploads_are_private_to_their_creator(api: AsyncClient) -> None:
    created = await api.post(
        "/api/v1/devices/pixel-rooted/files/uploads", headers=auth("administrator")
    )
    upload = created.json()["id"]
    other = await api.get(f"/api/v1/files/uploads/{upload}", headers=auth("operator"))
    assert other.status_code == 403
