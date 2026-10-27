"""Persistent ADB TCP check and installation over fake rooted transports."""

import ipaddress
import shlex
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.adb.persistent import (
    BOOT_SCRIPT,
    SCRIPT_PATH,
    SOCKETS_MARKER,
    render_script,
    server_addresses,
)
from android_fleet.core.settings import Settings
from android_fleet.devices.models import ConnectionType, DeviceState
from android_fleet.devices.registry_models import DeviceRegistration
from android_fleet.execution.models import CommandResult
from android_fleet.main import create_app

ADMIN = {"Authorization": "Bearer pairing-admin"}
HOST = "192.168.20.30"
SERVER = "192.168.20.5"
KEY = "QAAAAFakeServerKey== fleet@server"


def ipv4_hex(address: str) -> str:
    return ipaddress.IPv4Address(address).packed[::-1].hex().upper()


def tcp_row(local_port: int, remote: str, *, v6: bool = False, state: str = "01") -> str:
    local, peer = ipv4_hex(HOST), ipv4_hex(remote)
    if v6:
        local, peer = "0000000000000000FFFF0000" + local, "0000000000000000FFFF0000" + peer
    return f"   0: {local}:{local_port:04X} {peer}:C350 {state} 00000000:00000000 0"


def app_for(tmp_path: Path, adb: FakeAdbClient):  # type: ignore[no-untyped-def]
    return create_app(
        adb,
        Settings(
            registry_path=tmp_path / "devices.sqlite3",
            history_path=tmp_path / "history.sqlite3",
            seed_fake_devices=False,
            control_token=SecretStr("pairing-admin"),
            pairing_allowed_hosts=(HOST,),
        ),
    )


class PhoneAdb(FakeAdbClient):
    """A rooted Magisk phone whose root scripts are interpreted, not executed."""

    def __init__(self) -> None:
        super().__init__()
        self.rooted = True
        self.magisk = True
        self.script: str | None = None
        self.keys: set[str] = set()
        self.tcp_port = ""
        self.peer = SERVER
        self.firewall_runs = 0
        self.identity = "stable-test-android"

    def tables(self) -> str:
        local_port = 5555 if self.tcp_port == "5555" else 37000
        header = "  sl  local_address rem_address   st"
        return "\n".join(
            (header, tcp_row(local_port, self.peer, v6=True), tcp_row(8022, "192.168.20.9"))
        )

    async def enable_tcp(self, serial: str, *, timeout: float = 10) -> CommandResult:
        self.tcp_port = "5555"
        return await super().enable_tcp(serial, timeout=timeout)

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        if argv == ("su", "-c", "id -u"):
            if self.rooted:
                return CommandResult(stdout="0\n")
            return CommandResult(stderr="su: not found", exit_code=127)
        if argv == ("getprop",):
            result = await super().shell(serial, argv, timeout=timeout)
            return CommandResult(stdout=result.stdout + f"\n[ro.serialno]: [{self.identity}]\n")
        if argv[:2] != ("su", "-c") or len(argv) != 3:
            return await super().shell(serial, argv, timeout=timeout)
        self.calls.append((serial, argv))
        if not self.rooted:
            return CommandResult(stderr="su: not found", exit_code=127)
        script = argv[2]
        if SOCKETS_MARKER in script:
            report = [f"port={self.tcp_port}"]
            if self.script is not None:
                server = next(
                    line.split("=", 1)[1]
                    for line in self.script.splitlines()
                    if line.startswith("SERVER_IP=")
                )
                report += ["version=v2", f"server={server}"]
            if self.magisk:
                report.append("magisk=1")
            if KEY in self.keys:
                report.append("key=1")
            return CommandResult(stdout="\n".join([*report, SOCKETS_MARKER, self.tables()]))
        if script.endswith("echo installed"):
            # The quoted boot script spans lines, so scan tokens rather than lines.
            words = shlex.split(script)
            for index, word in enumerate(words):
                if words[index : index + 2] == ["printf", "%s"]:
                    self.script = words[index + 2]
                if word == "echo" and words[index + 2 : index + 3] == [">>"]:
                    self.keys.add(words[index + 1])
                if words[index : index + 3] == ["sh", SCRIPT_PATH, "--firewall"]:
                    self.firewall_runs += 1
            return CommandResult(stdout="installed\n")
        return await super().shell(serial, argv, timeout=timeout)


def test_server_addresses_decode_ipv4_and_mapped_ipv6_for_the_adb_port_only() -> None:
    tables = "\n".join(
        (
            "  sl  local_address rem_address   st",
            tcp_row(37000, SERVER),
            tcp_row(37000, SERVER, v6=True),
            tcp_row(37000, "192.168.20.7", state="0A"),
            tcp_row(8022, "192.168.20.9"),
            "garbage line",
        )
    )
    assert server_addresses(tables, 37000) == {ipaddress.IPv4Address(SERVER)}
    assert server_addresses(tables, 5555) == set()


def test_rendered_script_matches_device_setup_copy() -> None:
    assert "SERVER_IP=192.168.20.5\n" in render_script(SERVER)
    with pytest.raises(ValueError):
        render_script("192.168.20.5; reboot")
    copy = Path(__file__).parents[2] / "device-setup" / "magisk" / "adb_tcp.sh"
    if not copy.exists():
        pytest.skip("device-setup is not part of this checkout")
    assert copy.read_text(encoding="utf-8").replace("\r\n", "\n") == BOOT_SCRIPT


async def register(app, adb: PhoneAdb) -> str:  # type: ignore[no-untyped-def]
    device = await app.state.fleet.register(
        DeviceRegistration(
            "Pixel",
            ConnectionType.WIRELESS_ADB,
            HOST,
            37000,
            metadata={"wireless_identity": adb.identity},
        )
    )
    return str(device.id)


async def test_install_on_wireless_device_switches_to_persistent_tcp(tmp_path: Path) -> None:
    adb = PhoneAdb()
    adb.endpoints[f"{HOST}:37000"] = DeviceState.ONLINE
    key = tmp_path / "adbkey.pub"
    key.write_text(KEY + "\n", encoding="ascii")
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        app.state.pairing.persistence.key_path = key
        device_id = await register(app, adb)
        path = f"/api/v1/devices/{device_id}/adb-tcp/persistence"
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            before = (await client.get(path)).json()
            assert before["state"] == "not_installed"
            assert before["server_ip"] == SERVER and before["key_authorized"] is False
            installed = await client.post(path)
            assert installed.status_code == 200, installed.text
            assert installed.json()["state"] == "persistent"
            assert installed.json()["tcp_port_active"] and installed.json()["key_authorized"]
            assert adb.script == render_script(SERVER) and adb.firewall_runs == 1
            config = app.state.fleet.configs[device_id]
            assert (config.connection_type, config.port) == (ConnectionType.ADB_TCP, 5555)
            assert "device.adb_tcp_persistent" in (await client.get("/api/v1/audit")).text
            # The new transport reports the same server; the check stays green.
            assert (await client.get(path)).json()["state"] == "persistent"
            adb.peer = "192.168.20.6"
            assert (await client.get(path)).json()["state"] == "outdated"


async def test_status_reports_root_and_magisk_requirements(tmp_path: Path) -> None:
    adb = PhoneAdb()
    adb.endpoints[f"{HOST}:37000"] = DeviceState.ONLINE
    adb.rooted = False
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        device_id = await register(app, adb)
        path = f"/api/v1/devices/{device_id}/adb-tcp/persistence"
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            assert (await client.get(path)).json()["state"] == "root_required"
            refused = await client.post(path)
            assert refused.status_code == 409 and adb.script is None
            adb.rooted, adb.magisk = True, False
            await app.state.fleet.refresh_capabilities(device_id)
            assert (await client.get(path)).json()["state"] == "magisk_required"
            assert (await client.get(path, headers={"Authorization": ""})).status_code == 401


async def test_install_without_a_detectable_server_address_changes_nothing(
    tmp_path: Path,
) -> None:
    adb = PhoneAdb()
    adb.endpoints[f"{HOST}:37000"] = DeviceState.ONLINE
    adb.peer = "127.0.0.1"
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        device_id = await register(app, adb)
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            response = await client.post(f"/api/v1/devices/{device_id}/adb-tcp/persistence")
            assert response.status_code == 409
            assert "LAN address" in response.text
            assert adb.script is None and adb.firewall_runs == 0
            assert app.state.fleet.configs[device_id].port == 37000
