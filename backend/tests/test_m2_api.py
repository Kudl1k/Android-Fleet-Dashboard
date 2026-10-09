from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.main import create_app
from android_fleet.metrics.history import HistoryError, MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def settings(path: Path | str = ":memory:") -> Settings:
    return Settings(
        anonymous_viewer=True,
        registry_path=":memory:",
        history_path=path,
        metrics_interval_seconds=3600,
        poll_interval_seconds=3600,
        control_token=SecretStr("test-token"),
    )


def history_range() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "start": (now - timedelta(hours=1)).isoformat(),
        "end": (now + timedelta(minutes=1)).isoformat(),
    }


async def test_metrics_reads_are_unauthenticated_and_do_not_execute_adb() -> None:
    adb = FakeAdbClient()
    app = create_app(adb, settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            calls = len(adb.calls)
            current = await client.get("/api/v1/devices/pixel-rooted/metrics")
            assert current.status_code == 200
            body = current.json()
            assert body["device_id"] == "pixel-rooted"
            assert body["state"] == "online"
            assert not body["stale"]
            assert body["observed_at"] is not None
            values = {value["name"]: value for value in body["values"]}
            assert values["battery_level"]["unit"] == "ratio"
            assert values["battery_level"]["kind"] == "gauge"
            assert values["battery_level"]["labels"] == {}
            history = await client.get(
                "/api/v1/devices/pixel-rooted/metrics/history", params=history_range()
            )
            assert history.status_code == 200
            assert history.json()["device_id"] == "pixel-rooted"
            assert history.json()["points"]
            assert (await client.get("/metrics")).status_code == 200
            assert len(adb.calls) == calls


async def test_current_metrics_stale_and_offline_values_are_absent() -> None:
    app = create_app(FakeAdbClient(), settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            old = datetime.now(UTC) - timedelta(seconds=100)
            app.state.fleet.snapshots["pixel-rooted"] = MetricSnapshot(
                "pixel-rooted", old, (MetricValue("battery_level", 0.5, "ratio"),)
            )
            stale = (await client.get("/api/v1/devices/pixel-rooted/metrics")).json()
            assert stale["stale"] is True
            assert stale["values"] == []
            assert stale["observed_at"] is not None
            output = (await client.get("/metrics")).text
            assert 'android_battery_level_ratio{device_id="pixel-rooted"}' not in output
            offline = (await client.get("/api/v1/devices/pixel-offline/metrics")).json()
            assert offline["state"] == "offline"
            assert offline["values"] == []
            assert offline["observed_at"] is None
            assert offline["stale"] is False
            app.state.fleet.devices["pixel-rooted"].state = DeviceState.OFFLINE
            offline = (await client.get("/api/v1/devices/pixel-rooted/metrics")).json()
            assert offline["values"] == []


async def test_metrics_unknown_devices_use_safe_404_errors() -> None:
    app = create_app(FakeAdbClient(), settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            for route in ("metrics", "metrics/history"):
                response = await client.get(
                    f"/api/v1/devices/missing/{route}", params=history_range()
                )
                assert response.status_code == 404
                assert set(response.json()["error"]) == {"code", "message"}


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-01-01T00:00:00"},
        {"start": "2020-01-01T00:00:00+00:00"},
        {"end": "2020-01-01T00:00:00+00:00"},
        {"metric": "arbitrary_name"},
        {"limit": "0"},
        {"limit": "10001"},
        {"cursor": "invalid"},
        {"cursor": "x" * 2049},
    ],
)
async def test_invalid_history_parameters_are_422(changes: dict[str, str]) -> None:
    app = create_app(FakeAdbClient(), settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            params = history_range()
            params.update(changes)
            response = await client.get(
                "/api/v1/devices/pixel-rooted/metrics/history", params=params
            )
            assert response.status_code == 422
            assert set(response.json()["error"]) == {"code", "message"}


async def test_history_pagination_preserves_flat_normalized_values() -> None:
    app = create_app(FakeAdbClient(), settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            params = history_range() | {"limit": "1"}
            first = (
                await client.get("/api/v1/devices/pixel-rooted/metrics/history", params=params)
            ).json()
            assert len(first["points"]) == 1
            assert first["next_cursor"]
            point = first["points"][0]
            assert {"observed_at", "name", "unit", "value", "kind", "labels"} <= point.keys()
            second = (
                await client.get(
                    "/api/v1/devices/pixel-rooted/metrics/history",
                    params=params | {"cursor": first["next_cursor"]},
                )
            ).json()
            assert second["points"][0] != point
            filtered = (
                await client.get(
                    "/api/v1/devices/pixel-rooted/metrics/history",
                    params=history_range() | {"metric": "battery_level"},
                )
            ).json()
            assert all(p["name"] == "battery_level" for p in filtered["points"])


async def test_history_failure_does_not_expose_diagnostics() -> None:
    class FailedHistory(MetricHistoryStore):
        async def query(self, *args: object, **kwargs: object) -> object:
            raise HistoryError("History operation failed")

    app = create_app(FakeAdbClient(), settings(), history=FailedHistory(":memory:"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/devices/pixel-rooted/metrics/history", params=history_range()
            )
            assert response.status_code == 503
            assert set(response.json()["error"]) == {"code", "message"}


async def test_history_survives_restart_without_real_devices(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    app = create_app(FakeAdbClient(), settings(path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            before = (
                await client.get(
                    "/api/v1/devices/pixel-rooted/metrics/history", params=history_range()
                )
            ).json()["points"]
            assert before
    restarted = create_app(FakeAdbClient(), settings(path))
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(restarted), base_url="http://test"
        ) as client:
            after = (
                await client.get(
                    "/api/v1/devices/pixel-rooted/metrics/history", params=history_range()
                )
            ).json()["points"]
            assert all(point in after for point in before)
