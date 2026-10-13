"""Application integration and crash recovery regressions without Android hardware."""

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.adb.subprocess import SubprocessAdbClient
from android_fleet.core.settings import Settings
from android_fleet.execution.models import CommandResult
from android_fleet.main import create_app
from android_fleet.screen.bridge import ScrcpyBridge


async def test_screen_routes_use_screen_permissions_and_protect_invalid_requests(
    tmp_path: Path,
) -> None:
    settings = Settings(
        registry_path=":memory:",
        history_path=tmp_path / "history.sqlite3",
        rbac_credentials=json.dumps(
            [
                {
                    "identity": "viewer",
                    "role": "viewer",
                    "token_hash": hashlib.sha256(b"viewer-token").hexdigest(),
                }
            ]
        ),
    )
    app = create_app(FakeAdbClient(), settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            route = "/api/v1/devices/pixel-stock/screen/sessions"
            assert (await client.post(route, json={})).status_code == 401
            assert (await client.post(route, json={"codec": "h265"})).status_code == 401
            headers = {"Authorization": "Bearer viewer-token"}
            response = await client.post(route, json={}, headers=headers)
            assert response.status_code == 201
            sid = response.json()["id"]
            assert (
                await client.delete(f"/api/v1/screen/sessions/{sid}", headers=headers)
            ).status_code == 200
            assert (
                await client.post(route, json={"max_fps": 61}, headers=headers)
            ).status_code == 422
            metrics = (await client.get("/metrics")).text
            assert "android_screen_active_sessions 0" in metrics
            assert sid not in metrics
    assert app.state.screens.reaper.done()


async def test_recovery_retains_offline_records_and_retries(tmp_path: Path) -> None:
    manifest = tmp_path / "transports.json"
    manifest.write_text(json.dumps({"01234567": {"serial": "fixture", "port": 43210}}))
    adb = FakeAdbClient()
    adb.shell = AsyncMock(side_effect=ConnectionError("offline"))
    adb.remove_forward = AsyncMock()
    bridge = ScrcpyBridge(adb, tmp_path / "server", state_path=manifest)
    assert await bridge.recover() == 1
    assert "01234567" in json.loads(manifest.read_text())
    adb.shell.side_effect = None
    adb.shell.return_value = CommandResult(exit_code=0)
    assert await bridge.retry_recovery() == 0
    assert json.loads(manifest.read_text()) == {}
    assert manifest.stat().st_mode & 0o777 == 0o600


async def test_owned_forward_removal_preserves_reused_port() -> None:
    adb = SubprocessAdbClient()
    adb._run = AsyncMock(
        return_value=CommandResult(
            stdout="fixture tcp:43210 localabstract:unrelated\n", exit_code=0
        )
    )
    await adb.remove_forward("fixture", 43210, socket="scrcpy_01234567")
    assert adb._run.await_count == 1
    adb._run.reset_mock()
    adb._run.side_effect = [
        CommandResult(stdout="fixture tcp:43210 localabstract:scrcpy_01234567\n", exit_code=0),
        CommandResult(exit_code=0),
    ]
    await adb.remove_forward("fixture", 43210, socket="scrcpy_01234567")
    assert adb._run.await_count == 2
