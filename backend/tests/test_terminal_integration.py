"""Disposable loopback SSH server: no physical device or external network access."""

import asyncio
import json
from typing import Any

import asyncssh
import pytest


class EchoSession(asyncssh.SSHServerSession[str]):
    def __init__(self, observations: list[tuple[str, Any]]) -> None:
        self.observations = observations
        self.channel: asyncssh.SSHServerChannel[str] | None = None

    def connection_made(self, chan: asyncssh.SSHServerChannel[str]) -> None:
        self.channel = chan
        self.observations.append(("opened", None))

    def pty_requested(
        self, term_type: str, term_size: tuple[int, int, int, int], term_modes: Any
    ) -> bool:
        self.observations.append(("pty", (term_type, term_size)))
        return True

    def shell_requested(self) -> bool:
        return True

    def session_started(self) -> None:
        assert self.channel is not None
        self.channel.write("\x1b[32mDisposable SSH terminal\x1b[0m\r\n")

    def data_received(self, data: str, datatype: int | None) -> None:
        self.observations.append(("input", data))
        assert self.channel is not None
        self.channel.write(data)

    def terminal_size_changed(self, width: int, height: int, pixwidth: int, pixheight: int) -> None:
        self.observations.append(("resize", (width, height)))

    def connection_lost(self, exc: Exception | None) -> None:
        self.observations.append(("closed", None))


class TestSSHServer(asyncssh.SSHServer):
    __test__ = False

    def __init__(self, observations: list[tuple[str, Any]]) -> None:
        self.observations = observations

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == "disposable" and password == "ephemeral-test-password"

    def session_requested(self) -> EchoSession:
        return EchoSession(self.observations)


@pytest.fixture
async def ssh_server() -> Any:
    observations: list[tuple[str, Any]] = []
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_factory=lambda: TestSSHServer(observations),
        server_host_keys=[host_key],
        line_editor=False,
    )
    try:
        yield server.get_port(), host_key, observations
    finally:
        server.close()
        await server.wait_closed()


async def test_disposable_server_fixture_controls_and_resize(ssh_server: Any) -> None:
    port, key, observations = ssh_server
    known = f"[127.0.0.1]:{port} ".encode() + key.export_public_key()
    async with asyncssh.connect(
        "127.0.0.1",
        port,
        username="disposable",
        password="ephemeral-test-password",
        known_hosts=known,
        agent_path=None,
        client_keys=[],
    ) as connection:
        process = await connection.create_process(term_type="xterm-256color", term_size=(80, 24))
        assert "\x1b[32m" in await process.stdout.read(1024)
        process.stdin.write("\x03control")
        assert await process.stdout.read(1024) == "\x03control"
        process.change_terminal_size(120, 40)
        await asyncio.sleep(0.05)
        assert ("resize", (120, 40)) in observations
        process.close()
        await process.wait_closed()
    assert ("closed", None) in observations


@pytest.fixture
async def runtime(tmp_path: Any, ssh_server: Any) -> Any:
    import socket
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import uvicorn
    from cryptography.fernet import Fernet
    from fastapi import FastAPI
    from pydantic import SecretStr

    from android_fleet.core.settings import Settings
    from android_fleet.security import SecurityService
    from android_fleet.terminal.api import router
    from android_fleet.terminal.manager import TerminalManager
    from android_fleet.terminal.profiles import ProfileInput, ProfileService
    from android_fleet.terminal.ssh import SSHGateway

    port, key, observations = ssh_server
    profiles = ProfileService(
        tmp_path / "ssh.sqlite", Fernet.generate_key().decode(), [f"127.0.0.1:{port}"]
    )
    await profiles.initialize()
    profile = await profiles.save(
        ProfileInput(
            name="Disposable",
            host="127.0.0.1",
            port=port,
            username="disposable",
            auth_method="password",
            credential=SecretStr("ephemeral-test-password"),
        )
    )
    await profiles._query(
        "UPDATE ssh_profiles SET host_key=? WHERE id=?",
        (key.export_public_key().decode(), profile.id),
    )
    security = SecurityService(
        Settings(control_token="integration-secret"), tmp_path / "audit.sqlite"
    )
    settings = SimpleNamespace(
        terminal_path=tmp_path / "terminal.sqlite",
        registry_path=tmp_path / "registry.sqlite",
        terminal_adb_enabled=False,
        terminal_max_sessions=4,
        terminal_max_per_user=4,
        terminal_max_per_device=2,
        terminal_queue_chunks=16,
        terminal_idle_seconds=300,
        terminal_lifetime_seconds=3600,
        terminal_allowed_origins=("http://localhost:8088",),
    )
    manager = TerminalManager(settings, None, security, SSHGateway(profiles))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        await security.initialize()
        await manager.initialize()
        yield
        await manager.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router(manager, security))
    app.include_router(profiles.router(security))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    http_port = listener.getsockname()[1]
    config = uvicorn.Config(
        app, host="127.0.0.1", port=http_port, log_level="error", ws_max_size=4096, ws_max_queue=8
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:  # noqa: ASYNC110 - Uvicorn exposes no startup event
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{http_port}", profile, manager, observations, profiles
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


async def test_real_gateway_websocket_concurrency_resize_controls_cleanup(runtime: Any) -> None:
    import httpx
    import websockets

    base, profile, manager, observations, _ = runtime
    headers = {"Authorization": "Bearer integration-secret"}
    streams = []
    async with httpx.AsyncClient(base_url=base, headers=headers) as client:
        try:
            for _ in range(2):
                response = await client.post(
                    "/api/v1/terminal/sessions",
                    json={"connection_type": "ssh", "profile_id": profile.id},
                )
                assert response.status_code == 201, response.text
                sid = response.json()["id"]
                ticket = (await client.post(f"/api/v1/terminal/sessions/{sid}/ticket")).json()[
                    "ticket"
                ]
                ws = await websockets.connect(
                    base.replace("http:", "ws:") + f"/api/v1/terminal/sessions/{sid}/stream",
                    origin="http://localhost:8088",
                    subprotocols=["fleet-terminal.v1", "ticket." + ticket],
                )
                streams.append((sid, ws))
                assert json.loads(await ws.recv())["state"] == "active"
                assert "\x1b[32m" in json.loads(await ws.recv())["data"]
            assert manager.metrics()["active_ssh"] == 2
            for _, ws in streams:
                await ws.send(json.dumps({"version": 1, "type": "input", "data": "\x03test"}))
                assert json.loads(await ws.recv())["data"] == "\x03test"
                await ws.send(json.dumps({"version": 1, "type": "resize", "cols": 123, "rows": 45}))
                await ws.send(json.dumps({"version": 1, "type": "heartbeat"}))
                assert json.loads(await ws.recv())["type"] == "heartbeat"
            await asyncio.sleep(0.05)
            assert observations.count(("resize", (123, 45))) == 2
        finally:
            for _, ws in streams:
                await ws.close()
        async with asyncio.timeout(3):
            while manager.metrics()["active_ssh"]:  # noqa: ASYNC110 - verify external disconnect
                await asyncio.sleep(0.01)
        assert observations.count(("closed", None)) == 2
        history = (await client.get("/api/v1/terminal/sessions")).json()["items"]
        assert len(history) == 2
        assert all(item["termination_reason"] == "browser_disconnected" for item in history)
        assert "ephemeral-test-password" not in json.dumps(history)
        assert all(manager.sessions[sid].task.done() for sid, _ in streams)


async def test_changed_host_key_and_profile_acl_reject_before_session(runtime: Any) -> None:
    import httpx

    base, profile, manager, _, profiles = runtime
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": "Bearer integration-secret"}
    ) as client:
        replacement = asyncssh.generate_private_key("ssh-ed25519")
        await profiles._query(
            "UPDATE ssh_profiles SET host_key=? WHERE id=?",
            (replacement.export_public_key().decode(), profile.id),
        )
        response = await client.post(
            "/api/v1/terminal/sessions", json={"connection_type": "ssh", "profile_id": profile.id}
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "Terminal connection failed"
        assert manager.metrics()["active_ssh"] == 0
        assert manager.metrics()["creation_failures"] == 1
        assert next(iter(manager.sessions.values())).termination_reason == "connection_failed"


async def test_real_gateway_key_authentication(ssh_server: Any, tmp_path: Any) -> None:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from android_fleet.security import Actor
    from android_fleet.terminal.profiles import ProfileInput, ProfileService
    from android_fleet.terminal.ssh import SSHGateway

    _, host_key, _ = ssh_server
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    observations: list[tuple[str, Any]] = []

    class KeyServer(TestSSHServer):
        def password_auth_supported(self) -> bool:
            return False

        def public_key_auth_supported(self) -> bool:
            return True

        def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
            return username == "disposable" and key == client_key.convert_to_public()

    server = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_factory=lambda: KeyServer(observations),
        server_host_keys=[host_key],
        line_editor=False,
    )
    port = server.get_port()
    profiles = ProfileService(
        tmp_path / "key-ssh.sqlite", Fernet.generate_key().decode(), [f"127.0.0.1:{port}"]
    )
    await profiles.initialize()
    profile = await profiles.save(
        ProfileInput(
            name="Key auth",
            host="127.0.0.1",
            port=port,
            username="disposable",
            auth_method="key",
            credential=SecretStr(client_key.export_private_key().decode()),
        )
    )
    await profiles._query(
        "UPDATE ssh_profiles SET host_key=? WHERE id=?",
        (host_key.export_public_key().decode(), profile.id),
    )
    actor = Actor("administrator", "administrator", frozenset({"terminal:ssh"}))
    transport = None
    try:
        transport = await SSHGateway(profiles).open(profile.id, actor, 80, 24)
        assert b"\x1b[32m" in await transport.read()
        await transport.write(b"\x03key-auth")
        assert await transport.read() == b"\x03key-auth"
        await transport.resize(130, 50)
        await asyncio.sleep(0.05)
        assert ("resize", (130, 50)) in observations
    finally:
        if transport:
            await transport.close()
        server.close()
        await server.wait_closed()
    assert ("closed", None) in observations
