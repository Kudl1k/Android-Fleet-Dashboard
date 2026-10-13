from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.security import SecurityService
from android_fleet.terminal.api import router
from android_fleet.terminal.manager import TerminalManager


@pytest.fixture
def client(tmp_path: Path) -> Any:
    settings = Settings(control_token="test-secret")
    security = SecurityService(settings, tmp_path / "audit.sqlite")
    terminal_settings = SimpleNamespace(
        terminal_path=tmp_path / "terminals.sqlite",
        registry_path=tmp_path / "registry.sqlite",
        terminal_adb_enabled=True,
        terminal_max_sessions=4,
        terminal_max_per_user=3,
        terminal_max_per_device=3,
        terminal_queue_chunks=16,
        terminal_idle_seconds=300,
        terminal_lifetime_seconds=3600,
        terminal_allowed_origins=("http://localhost:8088",),
    )
    device = Device(
        "registered",
        "pixel-stock",
        "Stock",
        DeviceState.ONLINE,
        capabilities={DeviceCapability.ADB_SHELL},
    )
    manager = TerminalManager(
        terminal_settings,
        SimpleNamespace(adb=FakeAdbClient(), get=lambda _: device),
        security,
        None,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        await security.initialize()
        await manager.initialize()
        yield
        await manager.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router(manager, security))
    with TestClient(app) as instance:
        yield instance, manager


HEADERS = {"Authorization": "Bearer test-secret"}
BODY = {"connection_type": "adb", "device_id": "registered"}


def test_auth_and_schema(client: Any) -> None:
    http, _ = client
    assert http.post("/api/v1/terminal/sessions", json=BODY).status_code == 401
    assert (
        http.post(
            "/api/v1/terminal/sessions", json={**BODY, "serial": "arbitrary"}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        http.post(
            "/api/v1/terminal/sessions", json={**BODY, "cols": 0}, headers=HEADERS
        ).status_code
        == 422
    )


def test_real_bidirectional_websocket_and_cleanup(client: Any) -> None:
    http, manager = client
    response = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS)
    assert response.status_code == 201, response.text
    sid = response.json()["id"]
    ticket = http.post(f"/api/v1/terminal/sessions/{sid}/ticket", headers=HEADERS).json()["ticket"]
    with http.websocket_connect(
        f"/api/v1/terminal/sessions/{sid}/stream",
        headers={"origin": "http://localhost:8088"},
        subprotocols=["fleet-terminal.v1", "ticket." + ticket],
    ) as socket:
        assert socket.accepted_subprotocol == "fleet-terminal.v1"
        assert socket.receive_json()["state"] == "active"
        assert "\x1b[32m" in socket.receive_json()["data"]
        socket.send_json({"version": 1, "type": "input", "data": "hello\x03"})
        assert socket.receive_json()["data"] == "hello\x03"
        socket.send_json({"version": 1, "type": "resize", "cols": 100, "rows": 35})
        socket.send_json({"version": 1, "type": "heartbeat"})
        assert socket.receive_json()["type"] == "heartbeat"
        socket.send_json({"version": 1, "type": "close"})
        assert socket.receive_json()["state"] == "closed"
    assert manager.sessions[sid].transport.closed


def test_origin_and_ticket_rejection_before_accept(client: Any) -> None:
    http, _ = client
    sid = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS).json()["id"]
    for origin, protocols in [
        ("https://evil.example", ["fleet-terminal.v1", "ticket.fake"]),
        ("http://localhost:8088", ["fleet-terminal.v1", "ticket.fake"]),
        ("http://localhost:8088", []),
    ]:
        with pytest.raises(WebSocketDisconnect):
            with http.websocket_connect(
                f"/api/v1/terminal/sessions/{sid}/stream",
                headers={"origin": origin},
                subprotocols=protocols,
            ):
                pass


@pytest.mark.parametrize("message", ["{", '{"version":1,"type":"unknown"}', "x" * 8193])
def test_malformed_oversized_closes_session(client: Any, message: str) -> None:
    http, manager = client
    sid = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS).json()["id"]
    token = http.post(f"/api/v1/terminal/sessions/{sid}/ticket", headers=HEADERS).json()["ticket"]
    with http.websocket_connect(
        f"/api/v1/terminal/sessions/{sid}/stream",
        headers={"origin": "http://localhost:8088"},
        subprotocols=["fleet-terminal.v1", "ticket." + token],
    ) as socket:
        socket.receive_json()
        socket.receive_json()
        socket.send_text(message)
        error = socket.receive_json()
        assert error == {
            "version": 1,
            "type": "error",
            "code": "invalid_message",
            "detail": "Terminal message was invalid.",
        }
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert manager.sessions[sid].state == "failed"
    assert manager.runtime_failures == 1


@pytest.mark.parametrize("version", [True, 1.0, "1", False, 2])
def test_protocol_version_requires_exact_integer(client: Any, version: Any) -> None:
    from android_fleet.terminal.models import TerminalMessage

    with pytest.raises(ValueError):
        TerminalMessage.model_validate({"version": version, "type": "heartbeat"})


def test_creation_rejections_are_audited_and_counted(client: Any) -> None:
    http, manager = client
    assert http.post("/api/v1/terminal/sessions", json=BODY).status_code == 401
    assert manager.authentication_failures == 1
    manager.settings.terminal_adb_enabled = False
    response = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS)
    assert response.status_code == 403
    assert manager.authentication_failures == 2
    assert manager.failures == 1
    import sqlite3

    with sqlite3.connect(manager.security.path) as db:
        events = db.execute("SELECT action,authorization,outcome,error FROM audit").fetchall()
    assert ("terminal.create", "denied", "rejected", "permission_denied") in events


def test_admin_termination_audits_actual_actor(client: Any) -> None:
    import sqlite3

    from android_fleet.security import ADMIN, Actor

    http, manager = client
    manager.security._credentials.append(
        (manager.security._digest("second-admin"), Actor("terminator", "administrator", ADMIN))
    )
    sid = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS).json()["id"]
    response = http.post(
        f"/api/v1/terminal/sessions/{sid}/terminate",
        headers={"Authorization": "Bearer second-admin"},
    )
    assert response.status_code == 200
    with sqlite3.connect(manager.security.path) as db:
        record = db.execute(
            "SELECT actor FROM audit WHERE action='terminal.admin_terminate'"
        ).fetchone()
    assert record[0] == "terminator"


def test_binary_input_is_rejected_with_sanitized_error(client: Any) -> None:
    http, manager = client
    sid = http.post("/api/v1/terminal/sessions", json=BODY, headers=HEADERS).json()["id"]
    token = http.post(f"/api/v1/terminal/sessions/{sid}/ticket", headers=HEADERS).json()["ticket"]
    with http.websocket_connect(
        f"/api/v1/terminal/sessions/{sid}/stream",
        headers={"origin": "http://localhost:8088"},
        subprotocols=["fleet-terminal.v1", "ticket." + token],
    ) as socket:
        socket.receive_json()
        socket.receive_json()
        socket.send_bytes(b"untrusted-binary-input")
        assert socket.receive_json()["code"] == "invalid_message"
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert manager.sessions[sid].transport.closed
    assert manager.sessions[sid].termination_reason == "invalid_message"
