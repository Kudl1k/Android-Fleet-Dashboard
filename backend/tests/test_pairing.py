"""Wireless Debugging wizard API exercises fake transports only."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.main import create_app

ADMIN = {"Authorization": "Bearer pairing-admin"}
HOST = "192.168.20.30"


def app_for(tmp_path: Path, adb: FakeAdbClient, **overrides: object):
    settings: dict[str, object] = {
        "registry_path": tmp_path / "devices.sqlite3",
        "history_path": tmp_path / "history.sqlite3",
        "seed_fake_devices": False,
        "control_token": SecretStr("pairing-admin"),
        "pairing_allowed_hosts": (HOST,),
        **overrides,
    }
    return create_app(
        adb,
        Settings(**settings),
    )


async def test_pair_connect_register_update_and_restart(tmp_path: Path) -> None:
    adb = FakeAdbClient()
    adb.endpoints[f"{HOST}:37000"] = DeviceState.ONLINE
    adb.endpoints[f"{HOST}:38000"] = DeviceState.ONLINE
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            paired = await client.post(
                "/api/v1/pairing/pair", json={"host": HOST, "port": 36000, "code": "123456"}
            )
            assert paired.json() == {"paired": True, "connected": False}
            unverified = await client.post(
                "/api/v1/pairing/register", json={"host": HOST, "port": 37000, "name": "Android"}
            )
            assert unverified.status_code == 409
            connected = await client.post(
                "/api/v1/pairing/connect", json={"host": HOST, "port": 37000}
            )
            assert connected.status_code == 200 and connected.json()["connected"]
            body = {"host": HOST, "port": 37000, "name": "Android"}
            registered = await client.post("/api/v1/pairing/register", json=body)
            assert registered.status_code == 201
            identifier = registered.json()["id"]
            assert (await client.post("/api/v1/pairing/register", json=body)).status_code == 409
            update = await client.post(
                f"/api/v1/devices/{identifier}/wireless-port", json={"host": HOST, "port": 38000}
            )
            assert update.status_code == 200 and update.json()["id"] == identifier
            audit = (await client.get("/api/v1/audit")).text
            assert "123456" not in audit and "device.pair" in audit
    restarted = app_for(tmp_path, adb)
    async with restarted.router.lifespan_context(restarted):
        assert restarted.state.fleet.configs[identifier].port == 38000
        assert not restarted.state.pairing.verified


@pytest.mark.parametrize(
    "body",
    [
        {"host": HOST, "port": 36000, "code": "abc123"},
        {"host": HOST, "port": 0, "code": "123456"},
        {"host": "127.0.0.1", "port": 36000, "code": "123456"},
        {"host": "169.254.169.254", "port": 36000, "code": "123456"},
        {"host": "8.8.8.8", "port": 36000, "code": "123456"},
    ],
)
async def test_pairing_validation_is_secret_free(tmp_path: Path, body: dict[str, object]) -> None:
    app = app_for(tmp_path, FakeAdbClient())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            response = await client.post("/api/v1/pairing/pair", json=body)
            assert response.status_code == 422
            assert str(body["code"]) not in response.text


async def test_pairing_authorization_allowlist_and_rate_limit(tmp_path: Path) -> None:
    app = app_for(tmp_path, FakeAdbClient(), pairing_attempts_per_minute=1)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            body = {"host": HOST, "port": 36000, "code": "123456"}
            assert (await client.post("/api/v1/pairing/pair", json=body)).status_code == 401
            denied = {**body, "host": "192.168.20.31"}
            assert (
                await client.post("/api/v1/pairing/pair", json=denied, headers=ADMIN)
            ).status_code == 403
            assert (
                await client.post("/api/v1/pairing/pair", json=body, headers=ADMIN)
            ).status_code == 200
            assert (
                await client.post("/api/v1/pairing/pair", json=body, headers=ADMIN)
            ).status_code == 429


async def test_pairing_accepts_hosts_inside_approved_private_cidr(tmp_path: Path) -> None:
    host = "192.168.20.77"
    app = app_for(
        tmp_path,
        FakeAdbClient(),
        pairing_allowed_hosts=("192.168.20.0/24",),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            allowed = await client.post(
                "/api/v1/pairing/pair", json={"host": host, "port": 36000, "code": "123456"}
            )
            assert allowed.status_code == 200
            outside = await client.post(
                "/api/v1/pairing/pair",
                json={"host": "192.168.21.77", "port": 36000, "code": "123456"},
            )
            assert outside.status_code == 403


async def test_pairing_network_settings_persist_and_control_authorized_pairing(
    tmp_path: Path,
) -> None:
    settings = {
        "pairing_allowed_hosts": (),
    }
    app = app_for(tmp_path, FakeAdbClient(), **settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            assert (await client.get("/api/v1/pairing/allowed-networks")).json() == {"networks": []}
            approved = await client.post(
                "/api/v1/pairing/allowed-networks", json={"network": "192.168.0.0/24"}
            )
            assert approved.status_code == 200
            assert approved.json()["networks"][0]["network"] == "192.168.0.0/24"
            paired = await client.post(
                "/api/v1/pairing/pair",
                json={"host": "192.168.0.31", "port": 36000, "code": "123456"},
            )
            assert paired.status_code == 200
    restarted = app_for(tmp_path, FakeAdbClient(), **settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(restarted), base_url="http://test", headers=ADMIN
        ) as client:
            listed = await client.get("/api/v1/pairing/allowed-networks")
            assert listed.json()["networks"][0]["network"] == "192.168.0.0/24"
            revoked = await client.request(
                "DELETE",
                "/api/v1/pairing/allowed-networks",
                json={"network": "192.168.0.0/24"},
            )
            assert revoked.json() == {"networks": []}
            denied = await client.post(
                "/api/v1/pairing/pair",
                json={"host": "192.168.0.31", "port": 36000, "code": "123456"},
            )
            assert denied.status_code == 403


async def test_pairing_network_settings_are_admin_only(tmp_path: Path) -> None:
    app = app_for(tmp_path, FakeAdbClient(), pairing_allowed_hosts=())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/api/v1/pairing/allowed-networks")).status_code == 401
            assert (
                await client.post(
                    "/api/v1/pairing/allowed-networks", json={"network": "192.168.1.0/24"}
                )
            ).status_code == 401


async def test_pairing_network_settings_reject_unbounded_cidrs(tmp_path: Path) -> None:
    app = app_for(tmp_path, FakeAdbClient(), pairing_allowed_hosts=())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            response = await client.post(
                "/api/v1/pairing/allowed-networks", json={"network": "10.0.0.0/8"}
            )
            assert response.status_code == 422
            assert "private LAN CIDR" in response.json()["error"]["message"]
            assert "10.0.0.0/8" not in response.json()["error"]["message"]
            assert (await client.get("/api/v1/pairing/allowed-networks")).json() == {"networks": []}


@pytest.mark.parametrize("network", ["0.0.0.0/0", "10.0.0.0/8", "172.16.0.0/12", "8.8.8.0/24"])
def test_pairing_network_config_rejects_broad_or_non_private_ranges(network: str) -> None:
    with pytest.raises(ValidationError):
        Settings(pairing_allowed_hosts=(network,))


class FailureAdb(FakeAdbClient):
    async def pair(self, address: str, code: str, *, timeout: float = 15) -> CommandResult:
        return CommandResult(exit_code=1, stderr=code)


class TimeoutAdb(FakeAdbClient):
    async def pair(self, address: str, code: str, *, timeout: float = 15) -> CommandResult:
        return CommandResult(exit_code=None, timeout=True)


@pytest.mark.parametrize("adb,status", [(FailureAdb(), 409), (TimeoutAdb(), 504)])
async def test_pairing_failures_sanitized(tmp_path: Path, adb: FakeAdbClient, status: int) -> None:
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            response = await client.post(
                "/api/v1/pairing/pair", json={"host": HOST, "port": 36000, "code": "123456"}
            )
            assert response.status_code == status and "123456" not in response.text
            assert "123456" not in (await client.get("/api/v1/audit")).text
            failed_connect = await client.post(
                "/api/v1/pairing/connect", json={"host": HOST, "port": 37000}
            )
            assert failed_connect.status_code == 409


async def test_invalid_unauthenticated_pair_is_denied_and_audited(tmp_path: Path) -> None:
    app = app_for(tmp_path, FakeAdbClient())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/pairing/pair", json={"host": HOST, "port": 36000, "code": "not-a-code"}
            )
            assert response.status_code == 401
            audit = await app.state.security.history()
            assert audit["items"][0]["authorization"] == "denied"
            assert "not-a-code" not in str(audit)


async def test_malformed_terminal_type_does_not_crash_validation(tmp_path: Path) -> None:
    app = app_for(tmp_path, FakeAdbClient())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            response = await client.post("/api/v1/terminal/sessions", json={"connection_type": []})
            assert response.status_code == 422


class IdentityAdb(FakeAdbClient):
    identity = "stable-test-android"

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        result = await super().shell(serial, argv, timeout=timeout)
        if argv == ("getprop",):
            return CommandResult(stdout=result.stdout + f"\n[ro.serialno]: [{self.identity}]\n")
        return result


async def test_stable_identity_duplicate_and_wrong_device_port_update(tmp_path: Path) -> None:
    adb = IdentityAdb()
    adb.endpoints[f"{HOST}:37000"] = DeviceState.ONLINE
    adb.endpoints[f"{HOST}:38000"] = DeviceState.ONLINE
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            await client.post("/api/v1/pairing/connect", json={"host": HOST, "port": 37000})
            registered = await client.post(
                "/api/v1/pairing/register", json={"host": HOST, "port": 37000, "name": "Android"}
            )
            identifier = registered.json()["id"]
            await client.post("/api/v1/pairing/connect", json={"host": HOST, "port": 38000})
            duplicate = await client.post(
                "/api/v1/pairing/register", json={"host": HOST, "port": 38000, "name": "Duplicate"}
            )
            assert duplicate.status_code == 409
            adb.identity = "different-android"
            refused = await client.post(
                f"/api/v1/devices/{identifier}/wireless-port", json={"host": HOST, "port": 38000}
            )
            assert refused.status_code == 409
            assert app.state.fleet.configs[identifier].port == 37000


@pytest.mark.parametrize("state", [DeviceState.OFFLINE, DeviceState.UNAUTHORIZED])
async def test_connection_requires_online_authorized_device(
    tmp_path: Path, state: DeviceState
) -> None:
    adb = FakeAdbClient()
    adb.endpoints[f"{HOST}:37000"] = state
    app = app_for(tmp_path, adb)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test", headers=ADMIN
        ) as client:
            result = await client.post(
                "/api/v1/pairing/connect", json={"host": HOST, "port": 37000}
            )
            assert result.status_code == 409
            assert not app.state.pairing.verified
