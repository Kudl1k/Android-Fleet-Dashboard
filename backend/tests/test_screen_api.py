"""REST and WebSocket ticket/origin enforcement without real ADB."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.screen.api import router
from android_fleet.screen.manager import ScreenManager
from android_fleet.screen.models import ScreenConfig
from android_fleet.security import SecurityService


@pytest.fixture
async def app(tmp_path):
    token = "test-operator"
    settings = Settings(
        rbac_credentials=json.dumps(
            [
                {
                    "identity": "op",
                    "role": "operator",
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                },
                {
                    "identity": "viewer",
                    "role": "viewer",
                    "token_hash": hashlib.sha256(b"test-viewer").hexdigest(),
                },
            ]
        )
    )
    security = SecurityService(settings, tmp_path / "audit.sqlite")
    await security.initialize()

    class FixtureStream:
        width = 100
        height = 200

        def __init__(self):
            self.close = AsyncMock()
            self.send_input = AsyncMock()

        async def packets(self):
            await asyncio.sleep(0.02)
            yield SimpleNamespace(config=True, keyframe=False, wire=lambda: b"codec-fixture")
            yield SimpleNamespace(config=False, keyframe=True, wire=lambda: b"frame-fixture")
            await asyncio.Event().wait()

    streams = []

    def start_stream(*args):
        stream = FixtureStream()
        streams.append(stream)
        return stream

    bridge = SimpleNamespace(start=AsyncMock(side_effect=start_stream), streams=streams)
    fleet = SimpleNamespace(
        get=lambda _: SimpleNamespace(
            state=DeviceState.ONLINE, serial="fixture", capabilities={"adb_shell"}, sdk=36
        )
    )
    manager = ScreenManager(None, fleet, security, settings, bridge=bridge)
    application = FastAPI()
    application.include_router(router(manager, security))
    yield application, manager, security
    await manager.close()


async def test_rest_auth_validation_and_ownership(app):
    application, manager, _ = app
    with TestClient(application) as client:
        assert client.get("/api/v1/screen/sessions").status_code == 401
        headers = {"Authorization": "Bearer test-operator"}
        invalid = client.post(
            "/api/v1/devices/phone/screen/sessions", headers=headers, json={"codec": "h265"}
        )
        assert invalid.status_code == 422
        response = client.post("/api/v1/devices/phone/screen/sessions", headers=headers, json={})
        assert response.status_code == 201
        sid = response.json()["id"]
        assert client.get(f"/api/v1/screen/sessions/{sid}", headers=headers).status_code == 200
        assert (
            client.get(
                f"/api/v1/screen/sessions/{sid}", headers={"Authorization": "Bearer test-viewer"}
            ).status_code
            == 403
        )
        assert client.delete(f"/api/v1/screen/sessions/{sid}", headers=headers).status_code == 200
    assert sid in manager.sessions


async def test_websocket_origin_and_invalid_ticket_audited(app):
    application, _, security = app
    with TestClient(application) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/v1/screen/sessions/missing/stream", headers={"Origin": "https://evil.example"}
            ):
                pass
        with client.websocket_connect(
            "/api/v1/screen/sessions/missing/stream", headers={"Origin": "http://127.0.0.1:8088"}
        ) as socket:
            socket.send_json({"ticket": "invalid"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    history = await security.history()
    assert {row["error"] for row in history["items"]} >= {
        "untrusted_origin",
        "invalid_stream_ticket",
    }


async def test_authenticated_websocket_frames_input_cleanup_and_audit(app):
    application, manager, security = app
    headers = {"Authorization": "Bearer test-operator"}
    with TestClient(application) as client:
        sid = client.post("/api/v1/devices/phone/screen/sessions", headers=headers, json={}).json()[
            "id"
        ]
        ticket = client.post(f"/api/v1/screen/sessions/{sid}/ticket", headers=headers).json()[
            "ticket"
        ]
        with client.websocket_connect(
            f"/api/v1/screen/sessions/{sid}/stream", headers={"Origin": "http://127.0.0.1:8088"}
        ) as socket:
            socket.send_json({"ticket": ticket})
            assert socket.receive_json()["type"] == "metadata"
            # Metadata can also be queued during startup before the attach handshake.
            message = socket.receive()
            if message.get("text"):
                assert json.loads(message["text"])["type"] == "metadata"
                message = socket.receive()
            assert message["bytes"] == b"codec-fixture"
            assert socket.receive_bytes() == b"frame-fixture"
            socket.send_json({"type": "nav", "key": "home"})
            assert socket.receive_json()["detail"] == "Exclusive control required"
            assert client.post(f"/api/v1/screen/sessions/{sid}/control", headers=headers).json()[
                "control"
            ]
            socket.send_json({"type": "key", "action": "down", "keycode": 59})
            socket.send_json({"type": "nav", "key": "home", "unexpected": True})
            assert socket.receive_json()["detail"] == "Invalid input"
            assert (
                client.delete(f"/api/v1/screen/sessions/{sid}/control", headers=headers).json()[
                    "control"
                ]
                is False
            )
            socket.send_json({"type": "ping"})
        assert (
            client.get(f"/api/v1/screen/sessions/{sid}", headers=headers).json()["state"]
            == "stopped"
        )
    session = manager.sessions[sid]
    assert not session.control and not session.attached
    manager.bridge.streams[0].close.assert_awaited()
    inputs = [call.args[0] for call in manager.bridge.streams[0].send_input.await_args_list]
    assert inputs == [
        {
            "type": "key",
            "action": "down",
            "pressure": 1.0,
            "buttons": 1,
            "keycode": 59,
            "repeat": 0,
            "meta": 0,
        },
        {"type": "key", "action": "up", "keycode": 59},
    ]
    errors = {item["error"] for item in (await security.history())["items"]}
    assert {"invalid_input", "control_not_owned"} <= errors


async def test_websocket_oversized_message_and_owner_stop(app):
    application, manager, _ = app
    headers = {"Authorization": "Bearer test-viewer"}
    with TestClient(application) as client:
        sid = client.post("/api/v1/devices/phone/screen/sessions", headers=headers, json={}).json()[
            "id"
        ]
        ticket = client.post(f"/api/v1/screen/sessions/{sid}/ticket", headers=headers).json()[
            "ticket"
        ]
        with client.websocket_connect(
            f"/api/v1/screen/sessions/{sid}/stream", headers={"Origin": "http://127.0.0.1:8088"}
        ) as socket:
            socket.send_json({"ticket": ticket})
            socket.receive_json()
            assert (
                client.post(f"/api/v1/screen/sessions/{sid}/control", headers=headers).status_code
                == 403
            )
            socket.send_text("x" * 4097)
            while True:
                message = socket.receive()
                if message["type"] == "websocket.close":
                    assert message["code"] == 1008
                    break
        assert (
            client.get(f"/api/v1/screen/sessions/{sid}", headers=headers).json()["state"]
            == "stopped"
        )
    assert not manager.sessions[sid].control


async def test_administrator_termination_and_scoped_credentials(app, tmp_path):
    application, manager, _ = app
    scoped = Settings(
        rbac_credentials=json.dumps(
            [
                {
                    "identity": "scoped",
                    "role": "operator",
                    "device_ids": ["allowed"],
                    "token_hash": hashlib.sha256(b"scope-token").hexdigest(),
                },
                {
                    "identity": "admin",
                    "role": "administrator",
                    "token_hash": hashlib.sha256(b"admin-token").hexdigest(),
                },
            ]
        )
    )
    security = SecurityService(scoped, tmp_path / "scoped-audit.sqlite")
    await security.initialize()
    # Test credentials and domain scoping directly.
    actor = security._credentials[0][1]
    assert actor.device_ids == frozenset({"allowed"})
    await security.authorize_device(actor, "allowed", "screen:control")
    with pytest.raises(HTTPException):
        await security.authorize_device(actor, "denied", "screen:view")
    with TestClient(application) as client:
        sid = client.post(
            "/api/v1/devices/phone/screen/sessions",
            headers={"Authorization": "Bearer test-operator"},
            json={},
        ).json()["id"]
    administrator = security._credentials[1][1]
    session = await manager.get(sid, administrator, terminate=True)
    await manager.stop(session, "administrator_terminated")
    assert session.termination_reason == "administrator_terminated"


async def test_slow_socket_send_timeout_drains_tasks_and_stream(app):
    application, manager, security = app
    owner = security._credentials[0][1]
    session = await manager.create("phone", owner, ScreenConfig())
    await asyncio.sleep(0)
    ticket = (await manager.ticket(session, owner))["ticket"]

    class SlowSocket:
        headers = {"origin": "http://127.0.0.1:8088"}

        def __init__(self):
            self.messages = 0
            self.close = AsyncMock()
            self.accept = AsyncMock()
            self.send_json = AsyncMock()

        async def receive_text(self):
            self.messages += 1
            if self.messages == 1:
                return json.dumps({"ticket": ticket})
            await asyncio.Event().wait()

        async def send_bytes(self, packet):
            await asyncio.Event().wait()

    socket = SlowSocket()
    endpoint = next(
        route.endpoint
        for route in router(manager, security).routes
        if getattr(route, "path", "").endswith("/{sid}/stream")
    )
    async with asyncio.timeout(7):
        await endpoint(session.id, socket)
    assert session.state == "stopped" and not session.attached
    manager.bridge.streams[0].close.assert_awaited()
    socket.close.assert_awaited_once_with(code=1008)
    assert session.task.done()
