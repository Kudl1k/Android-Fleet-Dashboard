import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.devices.registry import RegistryError, SQLiteDeviceRegistry
from android_fleet.devices.registry_models import RegisteredDevice
from android_fleet.main import create_app

TOKEN = {"Authorization": "Bearer testtoken"}


def configuration(path: Path, *, token: bool = True) -> Settings:
    return Settings(
        anonymous_viewer=True,
        seed_fake_devices=False,
        registry_path=path,
        control_token=SecretStr("testtoken") if token else None,
        enable_mdns=False,
    )


def registration(*, host: str = "192.0.2.1", auto_connect: bool = False) -> dict[str, object]:
    return {
        "name": "Test Pixel",
        "connection_type": "adb_tcp",
        "host": host,
        "port": 5555,
        "auto_connect": auto_connect,
    }


async def wait_online(app: FastAPI, client: AsyncClient, identifier: str) -> None:
    for _ in range(100):
        await app.state.fleet.poll()
        if (await client.get(f"/api/v1/devices/{identifier}")).json()["state"] == "online":
            return
        await asyncio.sleep(0.01)
    pytest.fail("Fake device never became online")


async def test_registration_persists_without_fabricating_online_state(tmp_path: Path) -> None:
    path = tmp_path / "devices.sqlite3"
    adb = FakeAdbClient()
    app = create_app(adb, configuration(path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/api/v1/devices")).json() == []
            response = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            assert response.status_code == 201
            identifier = response.json()["id"]
            assert response.json()["state"] != "online"
            assert (await client.get(f"/api/v1/devices/{identifier}")).status_code == 200
    assert app.state.worker.done()
    restarted = create_app(adb, configuration(path))
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(restarted), base_url="http://test"
        ) as client:
            devices = (await client.get("/api/v1/devices")).json()
            assert len(devices) == 1
            assert devices[0]["id"] == identifier
            assert devices[0]["state"] != "online"
            assert not adb.connection_calls


async def test_endpoint_update_keeps_id_and_delete_removes_device(tmp_path: Path) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            identifier = response.json()["id"]
            updated = await client.patch(
                f"/api/v1/devices/{identifier}", json={"host": "192.0.2.2"}, headers=TOKEN
            )
            assert updated.status_code == 200
            assert updated.json()["id"] == identifier
            assert updated.json()["host"] == "192.0.2.2"
            deleted = await client.delete(f"/api/v1/devices/{identifier}", headers=TOKEN)
            assert deleted.status_code in {200, 204}
            missing = await client.get(f"/api/v1/devices/{identifier}")
            assert missing.status_code == 404
            assert set(missing.json()["error"]) == {"code", "message"}


async def test_disconnect_clears_metrics_and_stays_disabled_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "devices.db"
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    app = create_app(adb, configuration(path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            identifier = response.json()["id"]
            connect = await client.post(f"/api/v1/devices/{identifier}/connect", headers=TOKEN)
            assert connect.status_code == 202
            await wait_online(app, client, identifier)
            metrics = (await client.get("/metrics")).text
            assert f'android_battery_level_ratio{{device_id="{identifier}"}}' in metrics
            refreshed = await client.post(
                f"/api/v1/devices/{identifier}/capabilities/refresh", headers=TOKEN
            )
            assert refreshed.status_code == 200
            assert (
                await client.get(f"/api/v1/devices/{identifier}/capabilities")
            ).status_code == 200
            disconnect = await client.post(
                f"/api/v1/devices/{identifier}/disconnect", headers=TOKEN
            )
            assert disconnect.status_code == 200
            metrics = (await client.get("/metrics")).text
            assert f'android_battery_level_ratio{{device_id="{identifier}"}}' not in metrics
            assert (await client.get(f"/api/v1/devices/{identifier}")).json()[
                "state"
            ] == "disconnected"
            offline_refresh = await client.post(
                f"/api/v1/devices/{identifier}/capabilities/refresh", headers=TOKEN
            )
            assert offline_refresh.status_code == 409
    attempts = len(adb.connection_calls)
    restarted = create_app(adb, configuration(path))
    async with restarted.router.lifespan_context(restarted):
        await restarted.state.fleet.poll()
        assert len(adb.connection_calls) == attempts
    assert restarted.state.worker.done()


async def test_invalid_duplicate_and_control_scope(tmp_path: Path) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            invalid = await client.post(
                "/api/v1/devices", json=registration(host="--help"), headers=TOKEN
            )
            assert invalid.status_code in {400, 422}
            assert set(invalid.json()["error"]) == {"code", "message"}
            created = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            identifier = created.json()["id"]
            duplicate = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            assert duplicate.status_code == 409
            assert set(duplicate.json()["error"]) == {"code", "message"}
            for suffix in ("commands", "reboot", "terminal", "packages"):
                assert (
                    await client.post(f"/api/v1/devices/{identifier}/{suffix}", headers=TOKEN)
                ).status_code == 404
            discovery = (await client.get("/api/v1/discovery/devices")).json()
            assert discovery["mdns_enabled"] is False
            assert "mdns_available" in discovery
            assert isinstance(discovery["devices"], list)


async def test_unauthorized_transport_not_promoted_by_successful_connect(tmp_path: Path) -> None:
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.UNAUTHORIZED
    app = create_app(adb, configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            created = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            identifier = created.json()["id"]
            assert (
                await client.post(f"/api/v1/devices/{identifier}/connect", headers=TOKEN)
            ).status_code == 202
            await app.state.fleet.poll()
            device = (await client.get(f"/api/v1/devices/{identifier}")).json()
            assert device["state"] == "unauthorized"
            assert device["capabilities"] == []
            assert not [call for call in adb.calls if call[0] == "192.0.2.1:5555"]


@pytest.mark.parametrize("client_host", ["192.0.2.100", "127.0.0.1"])
async def test_configured_token_required_even_on_loopback(tmp_path: Path, client_host: str) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app, client=(client_host, 12345)), base_url="http://test"
        ) as client:
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                denied = await client.post("/api/v1/devices", json=registration(), headers=headers)
                assert denied.status_code in {401, 403}
            allowed = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            assert allowed.status_code == 201


@pytest.mark.parametrize(
    ("client_host", "headers", "allowed"),
    [
        ("127.0.0.1", {}, False),
        ("::1", {}, False),
        ("192.0.2.100", {}, False),
        ("127.0.0.1", {"Origin": "http://evil.example"}, False),
        ("127.0.0.1", {"Origin": ""}, False),
        ("192.0.2.100", {"X-Forwarded-For": "127.0.0.1"}, False),
    ],
)
async def test_no_token_denies_control_even_on_direct_loopback(
    tmp_path: Path, client_host: str, headers: dict[str, str], allowed: bool
) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db", token=False))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app, client=(client_host, 12345)), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/devices", json=registration(), headers=headers)
            assert (response.status_code == 201) is allowed
            if not allowed:
                assert response.status_code in {401, 403}


async def test_patch_disable_auto_connect_survives_poll_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "devices.db"
    adb = FakeAdbClient()
    adb.endpoints["192.0.2.1:5555"] = DeviceState.ONLINE
    app = create_app(adb, configuration(path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            created = await client.post(
                "/api/v1/devices", json=registration(auto_connect=True), headers=TOKEN
            )
            identifier = created.json()["id"]
            await wait_online(app, client, identifier)
            disabled = await client.patch(
                f"/api/v1/devices/{identifier}", json={"auto_connect": False}, headers=TOKEN
            )
            assert disabled.status_code == 200
            assert disabled.json()["auto_connect"] is False
            assert disabled.json()["state"] == "disconnected"
            attempts = len(adb.connection_calls)
            await app.state.fleet.poll()
            assert len(adb.connection_calls) == attempts
    restarted = create_app(adb, configuration(path))
    async with restarted.router.lifespan_context(restarted):
        await restarted.state.fleet.poll()
        assert len(adb.connection_calls) == attempts
        assert restarted.state.fleet.get(identifier).state == DeviceState.DISCONNECTED


async def test_concurrent_disjoint_patches_do_not_lose_configuration(tmp_path: Path) -> None:
    class SlowReadsRegistry(SQLiteDeviceRegistry):
        async def get(self, device_id: str) -> RegisteredDevice:
            result = await super().get(device_id)
            # Widen the interval between reading configuration and applying a patch.
            await asyncio.sleep(0.01)
            return result

    path = tmp_path / "devices.db"
    app = create_app(FakeAdbClient(), configuration(path), registry=SlowReadsRegistry(path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            created = await client.post("/api/v1/devices", json=registration(), headers=TOKEN)
            identifier = created.json()["id"]
            responses = await asyncio.gather(
                client.patch(
                    f"/api/v1/devices/{identifier}", json={"name": "Revised"}, headers=TOKEN
                ),
                client.patch(
                    f"/api/v1/devices/{identifier}",
                    json={"metadata": {"location": "lab"}},
                    headers=TOKEN,
                ),
            )
            assert all(response.status_code == 200 for response in responses)
            device = (await client.get(f"/api/v1/devices/{identifier}")).json()
            assert device["name"] == "Revised"
            assert device["metadata"] == {"location": "lab"}


async def test_non_ascii_bearer_is_rejected_without_server_error(tmp_path: Path) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/devices",
                json=registration(),
                headers={b"authorization": b"Bearer caf\xe9"},
            )
            assert response.status_code in {401, 403}
            assert response.json()["error"]["code"] == "control_denied"


async def test_cancelled_lifespan_startup_closes_registry(tmp_path: Path) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingAdb(FakeAdbClient):
        async def list_devices(self) -> dict[str, DeviceState]:
            entered.set()
            await release.wait()
            return await super().list_devices()

    app = create_app(BlockingAdb(), configuration(tmp_path / "devices.db"))
    lifespan = app.router.lifespan_context(app)
    startup = asyncio.create_task(lifespan.__aenter__())
    await asyncio.wait_for(entered.wait(), timeout=1)
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    with pytest.raises(RegistryError):
        await app.state.registry.list()
    assert not hasattr(app.state, "worker")
    assert app.state.fleet.ready is False


@pytest.mark.parametrize("fields", [{"port": True}, {"auto_connect": "true"}])
async def test_registration_rejects_coerced_control_fields(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    app = create_app(FakeAdbClient(), configuration(tmp_path / "devices.db"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            body = registration()
            body.update(fields)
            response = await client.post("/api/v1/devices", json=body, headers=TOKEN)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_request"
            assert (await client.get("/api/v1/devices")).json() == []
