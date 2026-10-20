"""Optional provisioning uses fake ADB and HTTP transports; no real device or APK needed."""

import asyncio
import base64
import hashlib
import io
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import asyncssh
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.adb.subprocess import SubprocessAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import ConnectionType, Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.main import create_app
from android_fleet.security import Actor
from android_fleet.setup.catalog import APPS, ApkDownloader, AppArtifact, SetupError
from android_fleet.setup.service import DeviceSetup
from android_fleet.setup.termux import TermuxSSHVerifier, setup_command
from android_fleet.terminal.profiles import ProfileInput, ProfileService

HOST = "192.168.20.30"


def apk_bytes() -> bytes:
    pool = struct.pack("<HHIIIIII", 1, 28, 36, 1, 0, 0, 32, 0) + bytes(8)
    start = struct.pack("<HHI", 0x102, 16, 36) + bytes(28)
    end = struct.pack("<HHI", 0x103, 16, 24) + bytes(16)
    chunks = pool + start + end
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("AndroidManifest.xml", struct.pack("<HHI", 3, 8, len(chunks) + 8) + chunks)
    return output.getvalue()


@pytest.mark.parametrize("failure", [None, "checksum", "size", "redirect", "network"])
async def test_official_apk_download_is_bounded_and_verified(
    tmp_path: Path, failure: str | None
) -> None:
    data = apk_bytes()
    artifact = AppArtifact(
        "com.termux", "test", len(data), hashlib.sha256(data).hexdigest(), "test.apk"
    )
    requests = []

    def reply(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "network":
            raise httpx.ConnectError("private transport error", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/secrets"})
        payload = data + b"oversized" if failure == "size" else data
        if failure == "checksum":
            payload = b"x" * len(data)
        return httpx.Response(200, content=payload)

    path = tmp_path / "app.apk"
    downloader = ApkDownloader(httpx.MockTransport(reply))
    if failure:
        with pytest.raises(SetupError):
            await downloader.download(artifact, path)
        assert not path.exists()
    else:
        await downloader.download(artifact, path)
        assert path.read_bytes() == data
    assert len(requests) == 1 and str(requests[0].url) == "https://f-droid.org/repo/test.apk"


class SetupAdb(FakeAdbClient):
    def __init__(self) -> None:
        super().__init__()
        self.installed: set[str] = set()
        self.focus = True
        self.install_failure = False
        self.fail_download_install_number = 0
        self.user = "0"

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        self.calls.append((serial, argv))
        if argv[:2] == ("pm", "path"):
            return CommandResult(
                stdout="package:/data/app/base.apk" if argv[2] in self.installed else ""
            )
        if argv == ("am", "get-current-user"):
            return CommandResult(stdout=self.user)
        if argv == ("pm", "list", "packages", "-U", "com.termux"):
            return CommandResult(stdout="package:com.termux uid:10241\n")
        if argv in {("dumpsys", "window", "displays"), ("dumpsys", "window")}:
            focus = (
                "com.termux/com.termux.app.TermuxActivity"
                if self.focus
                else "com.example/.Activity"
            )
            return CommandResult(stdout="mCurrentFocus=Window{abc u0 " + focus + "}")
        if argv == ("ps", "-A", "-o", "UID,NAME"):
            return CommandResult(stdout="UID NAME\n10241 bash\n")
        return CommandResult(stdout="Starting: Intent")

    async def command(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 30
    ) -> CommandResult:
        self.calls.append((serial, argv))
        if self.install_failure:
            return CommandResult(exit_code=1, stderr="private device error")
        self.installed.add(APPS[len(self.installed)].package)
        return CommandResult(stdout="Success")


class Downloads(ApkDownloader):
    async def download(self, app: AppArtifact, path: Path) -> None:
        await asyncio.to_thread(path.write_bytes, apk_bytes())


class Verifier(TermuxSSHVerifier):
    async def verify(
        self, serial: str, host: str, username: str, private_key: str, nonce: str
    ) -> asyncssh.SSHKey:
        assert username == "u0_a241"
        asyncssh.import_private_key(private_key)
        return asyncssh.generate_private_key("ssh-ed25519")


async def setup_service(tmp_path: Path) -> tuple[DeviceSetup, SetupAdb, ProfileService]:
    adb = SetupAdb()
    device = Device(
        "device",
        HOST + ":5555",
        "Samsung",
        DeviceState.ONLINE,
        ConnectionType.ADB_TCP,
        capabilities={DeviceCapability.ADB_SHELL},
    )
    fleet = SimpleNamespace(get=lambda _: device, configs={"device": SimpleNamespace(host=HOST)})
    profiles = ProfileService(tmp_path / "ssh.sqlite3", Fernet.generate_key().decode(), [])
    await profiles.initialize()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    service = DeviceSetup(adb, fleet, profiles, artifacts, Downloads(), Verifier(adb))  # type: ignore[arg-type]
    return service, adb, profiles


@pytest.mark.parametrize("rooted", [False, True])
async def test_setup_installs_verifies_and_reuses_encrypted_managed_key(
    tmp_path: Path, rooted: bool
) -> None:
    service, adb, profiles = await setup_service(tmp_path)
    service.fleet.get("device").root_available = rooted
    progress = []
    result = await service.run("device", "setup.termux", progress.append)
    assert adb.installed == {"com.termux", "org.fdroid.fdroid"}
    assert not list(service.artifacts.glob("*.apk"))
    pid = str(result["profile_id"])
    profile = await profiles.get(pid)
    assert profile.enabled and profile.fingerprint
    assert profile.device_id == "device" and profile.port == 8022
    secret = await profiles.credentials(profile)
    assert secret.encode() not in profiles.path.read_bytes()
    assert "PRIVATE KEY" not in str(result) + str(progress) + profile.model_dump_json()
    await service.run("device", "setup.ssh", progress.append)
    assert (await profiles.credentials(await profiles.get(pid))) == secret
    assert len(await profiles.list(Actor("admin", "administrator", frozenset()))) == 1
    assert any(argv[:2] == ("input", "text") for _, argv in adb.calls)
    assert not any(argv[0] == "su" for _, argv in adb.calls)


async def test_existing_apps_are_not_reinstalled(tmp_path: Path) -> None:
    service, adb, _ = await setup_service(tmp_path)
    adb.installed.update(app.package for app in APPS)
    await service.run("device", "setup.termux", lambda _: None)
    assert not any(argv[0] == "install" for _, argv in adb.calls)


async def test_install_failure_cleans_artifact_and_never_types_commands(tmp_path: Path) -> None:
    service, adb, _ = await setup_service(tmp_path)
    adb.install_failure = True
    with pytest.raises(SetupError, match="APK installation"):
        await service.run("device", "setup.termux", lambda _: None)
    assert not list(service.artifacts.glob("*.apk"))
    assert not any(argv[:2] == ("input", "text") for _, argv in adb.calls)


@pytest.mark.parametrize("failure", ["offline", "encryption", "secondary_user"])
async def test_setup_preconditions_have_no_device_changes(tmp_path: Path, failure: str) -> None:
    service, adb, profiles = await setup_service(tmp_path)
    if failure == "offline":
        service.fleet.get("device").state = DeviceState.OFFLINE
    elif failure == "encryption":
        profiles.cipher = None
    else:
        adb.user = "10"
    with pytest.raises(SetupError):
        await service.run("device", "setup.termux", lambda _: None)
    assert not adb.installed


async def test_focus_loss_never_sends_enter(tmp_path: Path) -> None:
    service, adb, _ = await setup_service(tmp_path)
    adb.installed.add("com.termux")
    original = adb.shell
    calls = 0

    async def lose_focus(
        serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        nonlocal calls
        if argv in {("dumpsys", "window", "displays"), ("dumpsys", "window")}:
            calls += 1
            if calls >= 3:
                adb.focus = False
        return await original(serial, argv, timeout=timeout)

    adb.shell = lose_focus  # type: ignore[method-assign]
    with pytest.raises(SetupError, match="lost focus"):
        await service.run("device", "setup.ssh", lambda _: None)
    assert not any(argv == ("input", "keyevent", "66") for _, argv in adb.calls)


def test_bootstrap_has_only_public_key_and_key_only_authentication() -> None:
    key = asyncssh.generate_private_key("ssh-ed25519")
    command = setup_command(key.export_public_key().decode(), "a" * 32)
    payload = command.removeprefix("echo%s").split("|", 1)[0]
    script = base64.b64decode(payload).decode()
    assert "PasswordAuthentication no" in script and "KbdInteractiveAuthentication no" in script
    assert "PRIVATE KEY" not in script and "allow-external-apps" not in script
    assert "authorized_keys" in script and "chmod 600" in script
    assert "apt-get install" in script and "openssh" in script


async def test_managed_destination_does_not_authorize_other_devices_or_ports(
    tmp_path: Path,
) -> None:
    _, _, profiles = await setup_service(tmp_path)
    managed = await profiles.prepare_termux("device", HOST, "test", "u0_a241")
    assert await profiles.destination(managed) == HOST
    for body in (
        ProfileInput(name="bad", host=HOST, port=8022, username="u0_a241"),
        ProfileInput(name="bad", host=HOST, port=22, device_id="device", username="u0_a241"),
    ):
        with pytest.raises(HTTPException):
            await profiles.destination(body)


async def test_ssh_forwarding_is_fixed_and_rejects_remote_adb_servers() -> None:
    with patch.object(SubprocessAdbClient, "_run", new_callable=AsyncMock) as run:
        run.return_value = CommandResult(stdout="19022")
        assert await SubprocessAdbClient().forward_ssh("serial") == 19022
        run.assert_awaited_once_with(["-s", "serial", "forward", "tcp:0", "tcp:8022"], 10)
        with pytest.raises(RuntimeError):
            await SubprocessAdbClient(server_host="remote").forward_ssh("serial")


async def test_cancelled_verification_removes_forward() -> None:
    adb = SetupAdb()
    verifier = TermuxSSHVerifier(adb)
    entered = asyncio.Event()

    async def blocked(*args: object, **kwargs: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    with patch("asyncssh.get_server_host_key", side_effect=blocked):
        task = asyncio.create_task(verifier.verify("serial", HOST, "user", "key", "a" * 32))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert ("serial", ("forward", "--remove", "tcp:19022")) in adb.calls


async def test_setup_operations_require_admin_and_confirmation(tmp_path: Path) -> None:
    app = create_app(
        FakeAdbClient(),
        Settings(
            registry_path=tmp_path / "devices.db",
            history_path=tmp_path / "history.db",
            control_token=SecretStr("admin-token"),
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            path = "/api/v1/devices/pixel-stock/operations"
            assert (
                await client.post(path, json={"action": "setup.termux", "confirmed": True})
            ).status_code == 401
            result = await client.post(
                path,
                json={"action": "setup.termux"},
                headers={"Authorization": "Bearer admin-token"},
            )
            assert result.status_code == 400 and "confirmation" in result.text


async def test_verifier_performs_real_key_login_and_pins_adb_host_key() -> None:
    key = asyncssh.generate_private_key("ssh-ed25519")
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    nonce = "a" * 32

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username: str) -> bool:
            return True

        def public_key_auth_supported(self) -> bool:
            return True

        def validate_public_key(self, username: str, supplied: asyncssh.SSHKey) -> bool:
            return username == "u0_a241" and supplied == key.convert_to_public()

    async def handle(process: asyncssh.SSHServerProcess[str]) -> None:
        assert process.command == 'cat "$HOME/.ssh/fleet_setup_complete"; id -un'
        process.stdout.write(nonce + "\nu0_a241\n")
        process.exit(0)

    async with await asyncssh.create_server(
        Server,
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        process_factory=handle,
    ) as server:
        adb = SetupAdb()
        adb.forward_ssh = AsyncMock(return_value=server.get_port())  # type: ignore[method-assign]
        real_connect = asyncssh.connect

        def dial(host: str, port: int, **kwargs: object):
            if host == HOST:
                assert port == 8022 and kwargs["preferred_auth"] == "publickey"
                assert kwargs["known_hosts"] == ([host_key.convert_to_public()], [], [])
                return real_connect("127.0.0.1", server.get_port(), **kwargs)
            return real_connect(host, port, **kwargs)

        with patch("asyncssh.connect", side_effect=dial):
            verified = await TermuxSSHVerifier(adb).verify(
                "serial",
                HOST,
                "u0_a241",
                key.export_private_key().decode(),
                nonce,
            )
        assert verified == host_key.convert_to_public()
        assert ("serial", ("forward", "--remove", f"tcp:{server.get_port()}")) in adb.calls


async def test_api_runs_full_queued_setup_and_audits_without_secrets(tmp_path: Path) -> None:
    from android_fleet.devices.registry_models import DeviceRegistration

    adb = SetupAdb()
    adb.endpoints[HOST + ":5555"] = DeviceState.ONLINE
    app = create_app(
        adb,
        Settings(
            registry_path=tmp_path / "devices.db",
            history_path=tmp_path / "history.db",
            seed_fake_devices=False,
            control_token=SecretStr("admin-token"),
            ssh_encryption_key=SecretStr(Fernet.generate_key().decode()),
        ),
    )
    async with app.router.lifespan_context(app):
        device = await app.state.fleet.register(
            DeviceRegistration(
                "Samsung",
                ConnectionType.ADB_TCP,
                HOST,
                5555,
            )
        )
        manager = app.state.operations
        manager.setup.downloader = Downloads()
        manager.setup.verifier = Verifier(adb)
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"Authorization": "Bearer admin-token"},
        ) as client:
            response = await client.post(
                f"/api/v1/devices/{device.id}/operations",
                json={"action": "setup.termux", "confirmed": True},
            )
            assert response.status_code == 202
            await asyncio.gather(*list(manager.tasks.values()))
            result = (await client.get("/api/v1/operations/" + response.json()["id"])).json()
            assert result["state"] == "succeeded", result
            assert result["result"]["stage"] == "SSH login verified"
            audit = (await client.get("/api/v1/audit")).text
            assert "setup.termux" in audit and "PRIVATE KEY" not in audit + str(result)


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Window #10 Window{2a88413 u0 com.termux/com.termux.app.TermuxActivity}:\n", None),
        ("mCurrentFocus=Window{2a88413 u0 com.termux/com.termux.app.TermuxActivity}\n", True),
        ("mCurrentFocus=Window{2a88413 u0 com.termux/.app.TermuxActivity}\n", True),
        ("mCurrentFocus=Window{abc u0 com.android.systemui/.PermissionActivity}", False),
        ("mCurrentFocus=null", False),
        ("mCurrentFocus=Window{abc u10 com.termux/.app.TermuxActivity}", False),
        ("mCurrentFocus=Window{abc u0 com.termux/.app.TermuxActivityOther}", False),
    ],
)
def test_termux_focus_requires_current_primary_user_window(
    output: str, expected: bool | None
) -> None:
    from android_fleet.setup.readiness import termux_has_focus

    assert termux_has_focus(output) is expected


async def test_samsung_display_focus_allows_setup_and_missing_summary_falls_back(
    tmp_path: Path,
) -> None:
    service, adb, _ = await setup_service(tmp_path)
    adb.installed.add("com.termux")
    original = adb.shell
    calls = []

    async def samsung(serial: str, argv: tuple[str, ...], *, timeout: float = 10) -> CommandResult:
        calls.append(argv)
        if argv == ("dumpsys", "window", "windows"):
            return CommandResult(stdout="Window #10 Window{abc u0 com.termux/.app.TermuxActivity}:")
        return await original(serial, argv, timeout=timeout)

    adb.shell = samsung  # type: ignore[method-assign]
    await service.run("device", "setup.ssh", lambda _: None)
    assert ("dumpsys", "window", "displays") in calls
    assert ("input", "keyevent", "66") in calls

    async def older(serial: str, argv: tuple[str, ...], *, timeout: float = 10) -> CommandResult:
        if argv == ("dumpsys", "window", "displays"):
            return CommandResult(stdout="No focus fields in this summary")
        return await samsung(serial, argv, timeout=timeout)

    adb.shell = older  # type: ignore[method-assign]
    await service.run("device", "setup.ssh", lambda _: None)
    assert ("dumpsys", "window") in calls
