from httpx import ASGITransport, AsyncClient

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.main import create_app


async def test_lifespan_and_readonly_slice() -> None:
    adb = FakeAdbClient()
    app = create_app(
        adb,
        Settings(
            anonymous_viewer=True,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
            devices = (await client.get("/api/v1/devices")).json()
            assert len(devices) == 4
            metrics = (await client.get("/metrics")).text
            assert 'android_device_rooted{device_id="pixel-rooted"} 1.0' in metrics
            assert 'android_device_rooted{device_id="pixel-stock"} 0.0' in metrics
            assert 'android_battery_level_ratio{device_id="pixel-malformed"}' not in metrics
            assert (await client.post("/api/v1/devices/pixel-rooted/commands")).status_code == 404
            adb.devices["pixel-rooted"] = DeviceState.OFFLINE
            await app.state.fleet.poll()
            metrics = (await client.get("/metrics")).text
            assert 'android_battery_level_ratio{device_id="pixel-rooted"}' not in metrics
            assert 'android_device_rooted{device_id="pixel-rooted"}' not in metrics


async def test_adb_failure_readiness_and_stale_cleanup() -> None:
    class UnavailableAdb(FakeAdbClient):
        async def list_devices(self) -> dict[str, DeviceState]:
            raise OSError("missing adb executable")

    app = create_app(
        UnavailableAdb(),
        Settings(
            anonymous_viewer=True,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 503
            assert (await client.get("/api/v1/devices")).json() == []


async def test_collector_failure_does_not_suppress_other_metrics() -> None:
    from android_fleet.execution.models import CommandResult

    class FailingBatteryAdb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if argv == ("dumpsys", "battery"):
                raise RuntimeError("unsupported subsystem")
            return await super().shell(serial, argv, timeout=timeout)

    app = create_app(
        FailingBatteryAdb(),
        Settings(
            anonymous_viewer=True,
        ),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            metrics = (await client.get("/metrics")).text
            assert 'android_memory_total_bytes{device_id="pixel-rooted"}' in metrics
            assert 'android_battery_level_ratio{device_id="pixel-rooted"}' not in metrics
            assert 'android_device_up{device_id="pixel-rooted"} 1.0' in metrics
