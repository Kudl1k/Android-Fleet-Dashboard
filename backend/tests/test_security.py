import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from starlette.requests import Request

from android_fleet.core.settings import Settings
from android_fleet.security import ADMIN, OPERATOR, READ, Actor, SecurityService


def configured() -> Settings:
    return Settings(
        anonymous_viewer=True,
        rbac_credentials=SecretStr(
            json.dumps(
                [
                    {
                        "identity": role,
                        "role": role,
                        "token_hash": hashlib.sha256((role + "-secret").encode()).hexdigest(),
                    }
                    for role in ("viewer", "operator", "administrator")
                ]
            )
        ),
    )


def request(token: str | None = None) -> Request:
    headers = [(b"authorization", ("Bearer " + token).encode())] if token else []
    return Request({"type": "http", "headers": headers, "path": "/test", "path_params": {}})


@pytest.mark.parametrize(
    "role,permissions", [("viewer", READ), ("operator", OPERATOR), ("administrator", ADMIN)]
)
async def test_authorization_matrix(tmp_path: Path, role: str, permissions: frozenset[str]) -> None:
    security = SecurityService(configured(), tmp_path / "security.db")
    await security.initialize()
    for permission in ADMIN | {"arbitrary.shell"}:
        if permission in permissions:
            actor = await security.authorize(request(role + "-secret"), permission)
            assert actor.role == role
        else:
            with pytest.raises(HTTPException) as exc:
                await security.authorize(request(role + "-secret"), permission)
            assert exc.value.status_code == 403
    assert (await security.history())["total"] == len((ADMIN | {"arbitrary.shell"}) - permissions)


async def test_invalid_token_cannot_downgrade_or_escalate(tmp_path: Path) -> None:
    security = SecurityService(configured(), tmp_path / "security.db")
    await security.initialize()
    with pytest.raises(HTTPException) as exc:
        await security.authorize(request("invalid"), "device.read")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        await security.authorize(request(), "control.reboot")
    assert (await security.authorize(request(), "device.read")).role == "viewer"
    serialized = json.dumps(await security.history())
    assert "invalid" not in serialized
    assert "secret" not in serialized


async def test_legacy_token_and_anonymous_disabled(tmp_path: Path) -> None:
    security = SecurityService(
        Settings(control_token="legacy-secret", anonymous_viewer=False), tmp_path / "security.db"
    )
    await security.initialize()
    assert (
        await security.authorize(request("legacy-secret"), "audit.read")
    ).role == "administrator"
    with pytest.raises(HTTPException):
        await security.authorize(request(), "device.read")


async def test_audit_persists_filters_and_sanitizes(tmp_path: Path) -> None:
    path = tmp_path / "security.db"
    security = SecurityService(configured(), path)
    await security.initialize()
    actor = Actor("operator", "operator", OPERATOR)
    for device in ("a", "b", "a"):
        await security.audit(
            actor,
            device,
            "apps.launch",
            "request",
            "allowed",
            "failed",
            duration=0.4,
            error="ADB token=highly-sensitive",
        )
    await security.close()
    restored = SecurityService(configured(), path)
    await restored.initialize()
    page = await restored.history(device_id="a", limit=1, offset=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["duration"] == 0.4
    assert page["items"][0]["error"] is None
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE audit SET actor = 'forged'")


async def test_audit_api_requires_admin_and_has_no_mutation(tmp_path: Path) -> None:
    security = SecurityService(configured(), tmp_path / "security.db")
    await security.initialize()
    app = FastAPI()
    app.include_router(security.router())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/audit")).status_code == 403
        assert (
            await client.get("/api/v1/audit", headers={"Authorization": "Bearer operator-secret"})
        ).status_code == 403
        response = await client.get(
            "/api/v1/audit", headers={"Authorization": "Bearer administrator-secret"}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert (await client.delete("/api/v1/audit")).status_code == 405
        me = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer viewer-secret"})
        assert me.json()["permissions"] == sorted(READ)


@pytest.mark.parametrize(
    "value",
    [
        "{}",
        '[{"identity":"a","role":"root","token_hash":"a"}]',
        '[{"identity":"a","role":"viewer","token_hash":"raw-secret"}]',
    ],
)
def test_invalid_credentials_rejected_without_secret_echo(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="Invalid RBAC credential configuration"):
        SecurityService(Settings(rbac_credentials=SecretStr(value)), tmp_path / "security.db")


async def test_retention(tmp_path: Path) -> None:
    security = SecurityService(configured(), tmp_path / "security.db")
    await security.initialize()
    with sqlite3.connect(security.path) as db:
        db.execute(
            "INSERT INTO audit(timestamp,actor,role,action,request_id,authorization,outcome,"
            "duration) VALUES(0,'a','viewer','read','id','allowed','succeeded',0)"
        )
    await security.cleanup()
    assert (await security.history())["total"] == 0


@pytest.mark.parametrize("role", ["viewer", "operator", "administrator"])
async def test_existing_api_permission_boundary(tmp_path: Path, role: str) -> None:
    from android_fleet.adb.fake import FakeAdbClient
    from android_fleet.main import create_app

    settings = configured().model_copy(
        update={
            "registry_path": tmp_path / "registry.db",
            "history_path": tmp_path / "history.db",
            "seed_fake_devices": False,
        }
    )
    app = create_app(FakeAdbClient(), settings)
    headers = {"Authorization": "Bearer " + role + "-secret"}
    reads = [
        "/devices",
        "/discovery/devices",
        "/devices/absent",
        "/devices/absent/capabilities",
        "/devices/absent/metrics",
        "/devices/absent/metrics/history",
        "/alerts",
        "/alerts/rules",
    ]
    mutations = [
        ("POST", "/devices"),
        ("PATCH", "/devices/absent"),
        ("DELETE", "/devices/absent"),
        ("POST", "/devices/absent/connect"),
        ("POST", "/devices/absent/disconnect"),
        ("POST", "/devices/absent/capabilities/refresh"),
        ("POST", "/alerts/rules"),
        ("PATCH", "/alerts/rules/absent"),
        ("DELETE", "/alerts/rules/absent"),
        ("POST", "/alerts/absent/acknowledge"),
    ]
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            for path in reads:
                assert (await client.get("/api/v1" + path, headers=headers)).status_code not in {
                    401,
                    403,
                }
            for method, path in mutations:
                response = await client.request(method, "/api/v1" + path, headers=headers, json={})
                assert (response.status_code in {401, 403}) == (role != "administrator")


async def test_private_reads_and_rejected_audit_survive_restart(tmp_path: Path) -> None:
    from android_fleet.adb.fake import FakeAdbClient
    from android_fleet.main import create_app

    settings = configured().model_copy(
        update={
            "registry_path": tmp_path / "registry.db",
            "history_path": tmp_path / "history.db",
            "seed_fake_devices": False,
            "anonymous_viewer": False,
        }
    )
    for iteration in range(2):
        app = create_app(FakeAdbClient(), settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                assert (await client.get("/api/v1/devices")).status_code == 401
                page = await client.get(
                    "/api/v1/audit", headers={"Authorization": "Bearer administrator-secret"}
                )
                assert page.json()["total"] == iteration + 1
                assert page.json()["items"][0]["authorization"] == "denied"


async def test_denied_device_audit_uses_middleware_identifier(tmp_path: Path) -> None:
    security = SecurityService(configured(), tmp_path / "security.db")
    await security.initialize()
    incoming = request("viewer-secret")
    incoming.state.audit_device_id = "device-123"
    with pytest.raises(HTTPException):
        await security.authorize(incoming, "device.manage")
    assert (await security.history())["items"][0]["device_id"] == "device-123"


@pytest.mark.parametrize("identity", ["anonymous", "unauthenticated", "legacy-administrator"])
def test_reserved_identity_cannot_alias_actor(tmp_path: Path, identity: str) -> None:
    configured_tokens = json.dumps(
        [
            {
                "identity": identity,
                "role": "operator",
                "token_hash": "a" * 64,
            }
        ]
    )
    with pytest.raises(ValueError, match="Invalid RBAC credential configuration"):
        SecurityService(Settings(rbac_credentials=configured_tokens), tmp_path / "security.db")


async def test_newer_audit_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "security.db"
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA user_version=2")
    security = SecurityService(configured(), path)
    with pytest.raises(ValueError, match="schema is newer"):
        await security.initialize()


async def test_default_requires_authentication_for_sensitive_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANDROID_FLEET_ANONYMOUS_VIEWER", raising=False)
    security = SecurityService(Settings(), tmp_path / "security.db")
    await security.initialize()
    for permission in READ:
        with pytest.raises(HTTPException) as exc:
            await security.authorize(request(), permission)
        assert exc.value.status_code == 401
    assert (await security.history())["total"] == len(READ)


@pytest.mark.parametrize("device_id", ["audit", "operations", "apk", "auth"])
async def test_device_identifier_cannot_bypass_authentication(
    tmp_path: Path, device_id: str
) -> None:
    from android_fleet.adb.fake import FakeAdbClient
    from android_fleet.main import create_app

    settings = Settings(
        registry_path=tmp_path / "registry.db",
        history_path=tmp_path / "history.db",
        seed_fake_devices=False,
        anonymous_viewer=False,
    )
    app = create_app(FakeAdbClient(), settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            for suffix in ("", "/metrics", "/capabilities"):
                response = await client.get(f"/api/v1/devices/{device_id}{suffix}")
                assert response.status_code == 401
