"""SSH secret, destination, ACL and pinning security regression tests."""

from pathlib import Path

import asyncssh
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from android_fleet.security import Actor
from android_fleet.terminal.profiles import ProfileInput, ProfileService
from android_fleet.terminal.ssh import SSHGateway


@pytest.fixture
async def profiles(tmp_path: Path) -> ProfileService:
    service = ProfileService(
        tmp_path / "ssh.db", Fernet.generate_key().decode(), ["127.0.0.1:2222", "127.0.0.1:5037"]
    )
    await service.initialize()
    return service


def body(**kwargs: object) -> ProfileInput:
    values: dict[str, object] = dict(
        name="test",
        host="127.0.0.1",
        port=2222,
        username="user",
        auth_method="password",
        credential=SecretStr("secret-password"),
    )
    values.update(kwargs)
    return ProfileInput.model_validate(values)


async def test_encryption_and_secret_free_response(profiles: ProfileService) -> None:
    profile = await profiles.save(body())
    assert "secret-password" not in profile.model_dump_json()
    assert "credential" not in profile.model_dump()
    assert b"secret-password" not in profiles.path.read_bytes()
    assert await profiles.credentials(profile) == "secret-password"
    reopened = ProfileService(profiles.path, None, [])
    assert (await reopened.get(profile.id)).name == "test"
    with pytest.raises(HTTPException) as error:
        await reopened.credentials(profile)
    assert error.value.status_code == 503


async def test_destination_and_acl(profiles: ProfileService) -> None:
    for spec in [body(host="example.com"), body(port=5037)]:
        with pytest.raises(HTTPException) as error:
            await profiles.save(spec)
        assert error.value.status_code == 403
    profile = await profiles.save(body(allowed_identities=["allowed"]))
    allowed = Actor("allowed", "operator", frozenset({"terminal:ssh"}))
    denied = Actor("denied", "operator", frozenset({"terminal:ssh"}))
    assert (await profiles.authorize(profile.id, allowed)).id == profile.id
    with pytest.raises(HTTPException):
        await profiles.authorize(profile.id, denied)
    assert await profiles.list(denied) == []
    await profiles.save(body(enabled=False), profile.id)
    with pytest.raises(HTTPException):
        await profiles.authorize(profile.id, allowed)


async def test_credentials_replace_and_key_enrollment(profiles: ProfileService) -> None:
    profile = await profiles.save(body())
    admin = Actor("admin", "administrator", frozenset({"terminal:ssh"}))
    with pytest.raises(HTTPException) as error:
        await SSHGateway(profiles).open(profile.id, admin, 80, 24)
    assert error.value.status_code == 409
    key = asyncssh.generate_private_key("ssh-ed25519")
    await profiles._query(
        "UPDATE ssh_profiles SET host_key=? WHERE id=?",
        (key.export_public_key().decode(), profile.id),
    )
    await profiles.save(body(credential=SecretStr("new-password")), profile.id)
    assert await profiles.credentials(await profiles.get(profile.id)) == "new-password"
    # No approved fingerprint means an edit cannot retain an unapproved key.
    assert await profiles.host_key(profile.id) is None


@pytest.mark.parametrize(
    "values", [{"port": 0}, {"port": 65536}, {"host": "foo/path"}, {"username": "-x user"}]
)
def test_profile_validation(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        body(**values)


async def test_atomic_key_rotation(profiles: ProfileService) -> None:
    profile = await profiles.save(body())
    replacement = Fernet.generate_key().decode()
    await profiles.rotate_encryption_key(replacement)
    restored = ProfileService(profiles.path, replacement, [])
    assert await restored.credentials(profile) == "secret-password"


async def test_dns_rebinding_rejected(profiles: ProfileService) -> None:
    profile = await profiles.save(body())
    profile.destination_ip = "192.168.1.10"
    with pytest.raises(HTTPException) as error:
        await profiles.destination(profile)
    assert error.value.status_code == 409


async def test_invalid_encryption_key_is_sanitized(profiles: ProfileService) -> None:
    profile = await profiles.save(body())
    wrong = ProfileService(profiles.path, Fernet.generate_key().decode(), [])
    with pytest.raises(HTTPException) as error:
        await wrong.credentials(profile)
    assert error.value.status_code == 503
    assert "secret-password" not in error.value.detail


@pytest.mark.parametrize(
    "values",
    [
        {"port": "22"},
        {"enabled": "true"},
        {"allowed_identities": ["bad identity"]},
        {"credential": "x" * 65537},
    ],
)
def test_strict_profile_security_validation(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        body(**values)


async def test_profile_rest_redaction_and_failure_audit(
    profiles: ProfileService, tmp_path: Path
) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from android_fleet.core.settings import Settings
    from android_fleet.security import SecurityService

    security = SecurityService(
        Settings(control_token=SecretStr("admin-token")), tmp_path / "audit.db"
    )
    await security.initialize()
    app = FastAPI()
    app.include_router(profiles.router(security))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"authorization": "Bearer admin-token"}
        response = await client.post(
            "/api/v1/ssh/profiles",
            headers=headers,
            json={
                "name": "test",
                "host": "127.0.0.1",
                "port": 2222,
                "username": "user",
                "auth_method": "password",
                "credential": "secret-password",
            },
        )
        assert response.status_code == 200
        assert "credential" not in response.json()
        assert "secret-password" not in response.text
        profile_id = response.json()["id"]
        result = await client.post(f"/api/v1/ssh/profiles/{profile_id}/test", headers=headers)
        assert result.status_code == 409
        denial = await client.get("/api/v1/ssh/profiles")
        assert denial.status_code == 401
    records = (await security.history())["items"]
    assert any(item["error"] == "connection_failed" for item in records)
    assert any(item["authorization"] == "denied" for item in records)
    assert "secret-password" not in str(records)


async def test_recorded_command_uses_quoted_time_wrapper(
    profiles: ProfileService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shlex
    from unittest.mock import AsyncMock

    profile = await profiles.save(body())
    key = asyncssh.generate_private_key("ssh-ed25519")
    await profiles._query(
        "UPDATE ssh_profiles SET host_key=? WHERE id=?",
        (key.export_public_key().decode(), profile.id),
    )
    connection = AsyncMock()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(asyncssh, "connect", connect)
    command = "printf '%s\\n' \"a'b\"; exit 7"
    actor = Actor("admin", "administrator", frozenset({"terminal:ssh"}))
    await SSHGateway(profiles).open(profile.id, actor, 80, 24, command)
    wrapped = connection.create_process.call_args.kwargs["command"]
    assert shlex.split(wrapped) == ["LC_ALL=C", "command", "time", "-v", "sh", "-c", command]
    assert connect.call_args.kwargs["known_hosts"]
