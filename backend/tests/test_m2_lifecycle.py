import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.core.settings import Settings
from android_fleet.devices.models import DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.main import create_app
from android_fleet.metrics.history import HistoryError


class BlockingMetricsAdb(FakeAdbClient):
    def __init__(self) -> None:
        super().__init__()
        self.devices = {"pixel-rooted": DeviceState.ONLINE}
        self.blocked_command: tuple[str, ...] | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        if argv == self.blocked_command:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        return await super().shell(serial, argv, timeout=timeout)


def settings(tmp_path: Path, **overrides: object) -> Settings:
    fields: dict[str, object] = {
        "registry_path": tmp_path / "devices.db",
        "history_path": tmp_path / "metrics.db",
        "seed_fake_devices": True,
        "metrics_command_timeout": 1,
        "metrics_cycle_timeout": 2,
    }
    fields.update(overrides)
    return Settings(**fields)


async def test_metrics_io_does_not_block_connectivity_poll(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path))
    async with app.router.lifespan_context(app):
        adb.blocked_command = ("dumpsys", "battery")
        collecting = asyncio.create_task(app.state.fleet.collect_metrics())
        await asyncio.wait_for(adb.entered.wait(), timeout=1)
        await asyncio.wait_for(app.state.fleet.poll(collect=False), timeout=0.2)
        assert not collecting.done()
        assert app.state.fleet.get("pixel-rooted").state == DeviceState.ONLINE
        adb.release.set()
        await collecting


async def test_disconnect_invalidates_inflight_snapshot_and_history(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path))
    async with app.router.lifespan_context(app):
        adb.blocked_command = ("dumpsys", "battery")
        started = datetime.now(UTC)
        collecting = asyncio.create_task(app.state.fleet.collect_metrics())
        await asyncio.wait_for(adb.entered.wait(), timeout=1)
        await asyncio.wait_for(app.state.fleet.disconnect("pixel-rooted"), timeout=0.2)
        assert "pixel-rooted" not in app.state.fleet.snapshots
        adb.release.set()
        await collecting
        assert "pixel-rooted" not in app.state.fleet.snapshots
        page = await app.state.history.query(
            "pixel-rooted", start=started, end=datetime.now(UTC) + timedelta(seconds=1)
        )
        assert page.points == ()
        assert app.state.fleet.get("pixel-rooted").state == DeviceState.DISCONNECTED


async def test_cycle_budget_keeps_completed_metrics(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path, metrics_command_timeout=1, metrics_cycle_timeout=0.05))
    async with app.router.lifespan_context(app):
        adb.blocked_command = ("cat", "/proc/meminfo")
        await asyncio.wait_for(app.state.fleet.collect_metrics(), timeout=1)
        current = app.state.fleet.snapshots["pixel-rooted"]
        names = {value.name for value in current.values}
        assert "battery_level" in names
        assert "memory_total" not in names
        assert adb.cancelled.is_set()


async def test_shutdown_drains_metrics_worker_and_child_io(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path, metrics_interval_seconds=1))
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    adb.blocked_command = ("dumpsys", "battery")
    await asyncio.wait_for(adb.entered.wait(), timeout=2)
    await asyncio.wait_for(lifespan.__aexit__(None, None, None), timeout=1)
    assert adb.cancelled.is_set()
    assert app.state.worker.done()
    assert app.state.metrics_worker.done()
    with pytest.raises(HistoryError):
        await app.state.history.prune()


async def test_cpu_baseline_resets_after_manual_disconnect(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path))
    async with app.router.lifespan_context(app):
        initial = app.state.fleet.snapshots["pixel-rooted"]
        assert "cpu_usage" not in {value.name for value in initial.values}
        await app.state.fleet.collect_metrics()
        assert "cpu_usage" in {
            value.name for value in app.state.fleet.snapshots["pixel-rooted"].values
        }
        await app.state.fleet.disconnect("pixel-rooted")
        await app.state.fleet.connect("pixel-rooted")
        assert "cpu_usage" not in {
            value.name for value in app.state.fleet.snapshots["pixel-rooted"].values
        }
        await app.state.fleet.collect_metrics()
        assert "cpu_usage" in {
            value.name for value in app.state.fleet.snapshots["pixel-rooted"].values
        }


async def test_history_persists_when_runtime_snapshots_are_disconnected(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    configuration = settings(tmp_path)
    app = create_app(adb, configuration)
    start = datetime.now(UTC) - timedelta(seconds=1)
    async with app.router.lifespan_context(app):
        assert app.state.fleet.snapshots["pixel-rooted"].values
        await app.state.fleet.disconnect("pixel-rooted")
    restarted = create_app(adb, configuration)
    async with restarted.router.lifespan_context(restarted):
        assert "pixel-rooted" not in restarted.state.fleet.snapshots
        page = await restarted.state.history.query(
            "pixel-rooted", start=start, end=datetime.now(UTC) + timedelta(seconds=1)
        )
        assert any(point.metric.name == "battery_level" for point in page.points)


async def test_successful_peer_and_prune_cannot_mask_history_append_failure(
    tmp_path: Path,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from android_fleet.metrics.history import MetricHistoryStore
    from android_fleet.metrics.models import MetricSnapshot

    class SelectiveFailureHistory(MetricHistoryStore):
        fail = True
        pruned = asyncio.Event()

        async def append(self, snapshot: MetricSnapshot) -> None:
            if self.fail and snapshot.device_id == "pixel-rooted":
                raise HistoryError("write failed")
            await super().append(snapshot)

        async def prune(self) -> None:
            await super().prune()
            self.pruned.set()

    history = SelectiveFailureHistory(tmp_path / "metrics.db")
    adb = FakeAdbClient()
    adb.devices = {"pixel-rooted": DeviceState.ONLINE, "pixel-stock": DeviceState.ONLINE}
    app = create_app(adb, settings(tmp_path, metrics_interval_seconds=1), history=history)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/ready")).status_code == 503
            # A later successful peer and successful pruning must retain the write failure.
            await asyncio.wait_for(history.pruned.wait(), timeout=2)
            assert (await client.get("/ready")).status_code == 503
            history.fail = False
            await app.state.fleet.collect_metrics()
            assert (await client.get("/ready")).status_code == 200


async def test_manual_poll_cannot_restore_readiness_after_worker_failure(tmp_path: Path) -> None:
    from httpx import ASGITransport, AsyncClient

    failed = asyncio.Event()
    app = create_app(BlockingMetricsAdb(), settings(tmp_path))

    async def failed_worker(interval: float) -> None:
        failed.set()
        raise RuntimeError("connectivity worker failed")

    app.state.fleet.run = failed_worker
    async with app.router.lifespan_context(app):
        await failed.wait()
        await asyncio.sleep(0)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert app.state.worker.done()
            assert (await client.get("/ready")).status_code == 503
            await app.state.fleet.poll()
            assert app.state.fleet.ready is True
            assert (await client.get("/ready")).status_code == 503


async def test_cancelled_waiter_does_not_cancel_shared_collection(tmp_path: Path) -> None:
    adb = BlockingMetricsAdb()
    app = create_app(adb, settings(tmp_path))
    async with app.router.lifespan_context(app):
        adb.blocked_command = ("dumpsys", "battery")
        started = datetime.now(UTC)
        first_waiter = asyncio.create_task(app.state.fleet.collect_metrics())
        await asyncio.wait_for(adb.entered.wait(), timeout=1)
        second_waiter = asyncio.create_task(app.state.fleet.collect_metrics())
        await asyncio.sleep(0)
        second_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second_waiter
        assert not adb.cancelled.is_set()
        assert not first_waiter.done()
        adb.release.set()
        await first_waiter
        assert "battery_level" in {
            value.name for value in app.state.fleet.snapshots["pixel-rooted"].values
        }
        page = await app.state.history.query(
            "pixel-rooted", start=started, end=datetime.now(UTC) + timedelta(seconds=1)
        )
        assert any(point.metric.name == "battery_level" for point in page.points)
    assert app.state.metrics_worker.done()
    assert not app.state.fleet._metric_tasks
    assert not app.state.fleet._retired_metric_tasks
