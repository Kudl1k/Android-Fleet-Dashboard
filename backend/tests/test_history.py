import asyncio
import base64
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from android_fleet.api.metric_models import current_response, history_response
from android_fleet.devices.models import Device, DeviceState
from android_fleet.metrics import history
from android_fleet.metrics.history import HistoryError, InvalidHistoryQuery, MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def snapshot(timestamp: datetime, *values: MetricValue, device_id: str = "pixel") -> MetricSnapshot:
    return MetricSnapshot(device_id, timestamp, values)


def memory(value: float = 100) -> MetricValue:
    return MetricValue("memory_total", value, "bytes")


def bounds(now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(seconds=100), now + timedelta(seconds=1)


async def test_persistence_upsert_and_metric_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "metrics.db"
    store = MetricHistoryStore(path)
    await store.initialize()
    now = datetime.now(UTC)
    await store.append(snapshot(now, memory(), memory(200)))
    await store.append(snapshot(now, memory(300)))
    await store.append(
        snapshot(now, MetricValue("network_receive", 42, "bytes", (("interface", "wlan0"),)))
    )
    await store.close()
    reopened = MetricHistoryStore(path)
    await reopened.initialize()
    start, end = bounds(now)
    page = await reopened.query("pixel", start=start, end=end)
    assert [(point.metric.name, point.metric.value) for point in page.points] == [
        ("memory_total", 300),
        ("network_receive", 42),
    ]
    assert page.points[0].observed_at == now
    assert page.points[1].metric.labels == (("interface", "wlan0"),)
    assert page.next_cursor is None
    await reopened.close()


async def test_invalid_metric_values_are_omitted() -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    now = datetime.now(UTC)
    await store.append(
        snapshot(
            now,
            memory(),
            MetricValue("secret/path", 1, "bytes"),
            MetricValue("battery_level", 2, "ratio"),
            MetricValue("memory_total", float("inf"), "bytes"),
            MetricValue("memory_available", 10, "wrong"),
            MetricValue("network_receive", 1, "bytes", (("interface", "raw unsafe/path"),)),
        )
    )
    start, end = bounds(now)
    page = await store.query("pixel", start=start, end=end)
    assert [point.metric for point in page.points] == [memory()]
    await store.close()


async def test_keyset_pagination_same_epoch_and_query_identity() -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    now = datetime.now(UTC)
    values = (
        memory(),
        MetricValue("memory_available", 50, "bytes"),
        MetricValue("network_receive", 1, "bytes", (("interface", "wlan0"),)),
        MetricValue("network_receive", 2, "bytes", (("interface", "eth0"),)),
    )
    await store.append(snapshot(now, *values))
    start, end = bounds(now)
    first = await store.query("pixel", start=start, end=end, limit=2)
    assert len(first.points) == 2
    assert first.next_cursor
    second = await store.query("pixel", start=start, end=end, limit=2, cursor=first.next_cursor)
    assert len(second.points) == 2
    assert second.next_cursor is None
    assert first.points + second.points == (await store.query("pixel", start=start, end=end)).points
    with pytest.raises(InvalidHistoryQuery):
        await store.query("other-device", start=start, end=end, cursor=first.next_cursor)
    with pytest.raises(InvalidHistoryQuery):
        await store.query(
            "pixel", start=start, end=end, metric="memory_total", cursor=first.next_cursor
        )
    with pytest.raises(InvalidHistoryQuery):
        await store.query(
            "pixel", start=start, end=end + timedelta(seconds=1), cursor=first.next_cursor
        )
    filtered = await store.query("pixel", start=start, end=end, metric="network_receive", limit=1)
    assert filtered.points[0].metric.labels == (("interface", "eth0"),)
    assert filtered.next_cursor
    tail = await store.query(
        "pixel",
        start=start,
        end=end,
        metric="network_receive",
        limit=1,
        cursor=filtered.next_cursor,
    )
    assert tail.points[0].metric.labels == (("interface", "wlan0"),)
    await store.close()


async def test_age_and_capacity_retention_on_append_query_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    current = [now.timestamp()]
    monkeypatch.setattr(history.time, "time", lambda: current[0])
    path = tmp_path / "history.db"
    store = MetricHistoryStore(path, retention_seconds=60, max_points=2)
    await store.initialize()
    await store.append(snapshot(now - timedelta(seconds=61), memory(1)))
    await store.append(snapshot(now - timedelta(seconds=10), memory(2)))
    await store.append(snapshot(now - timedelta(seconds=5), memory(3)))
    await store.append(snapshot(now, memory(4)))
    await store.append(snapshot(now, memory(5), device_id="other"))
    page = await store.query(
        "pixel", start=now - timedelta(seconds=59), end=now + timedelta(seconds=1)
    )
    assert [point.metric.value for point in page.points] == [4]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM samples").fetchone()[0] == 2
        assert connection.execute("SELECT point_count FROM history_stats").fetchone()[0] == 2
    current[0] += 61
    page = await store.query(
        "pixel", start=now - timedelta(seconds=59), end=now + timedelta(seconds=1)
    )
    assert page.points == ()
    await store.close()
    reopened = MetricHistoryStore(path, retention_seconds=60, max_points=1)
    await reopened.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM samples").fetchone()[0] == 0
    await reopened.close()


async def test_delete_device_and_capacity_reduction_restart(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    store = MetricHistoryStore(path, max_points=5)
    await store.initialize()
    now = datetime.now(UTC)
    await store.append(snapshot(now, memory(), device_id="remove"))
    await store.append(snapshot(now, memory(), MetricValue("memory_available", 20, "bytes")))
    await store.delete_device("remove")
    await store.prune()
    await store.close()
    smaller = MetricHistoryStore(path, max_points=1)
    await smaller.initialize()
    start, end = bounds(now)
    assert len((await smaller.query("pixel", start=start, end=end)).points) == 1
    assert not (await smaller.query("remove", start=start, end=end)).points
    await smaller.close()


@pytest.mark.parametrize("limit", [0, -1, 10001, True])
async def test_limit_validation(limit: int) -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    now = datetime.now(UTC)
    start, end = bounds(now)
    with pytest.raises(InvalidHistoryQuery):
        await store.query("pixel", start=start, end=end, limit=limit)
    await store.close()


async def test_range_metric_and_naive_datetime_validation() -> None:
    store = MetricHistoryStore(":memory:", retention_seconds=60)
    await store.initialize()
    now = datetime.now(UTC)
    for start, end in (
        (now, now),
        (now, now - timedelta(seconds=1)),
        (now - timedelta(seconds=61), now),
        (now.replace(tzinfo=None), now),
    ):
        with pytest.raises(InvalidHistoryQuery):
            await store.query("pixel", start=start, end=end)
    with pytest.raises(InvalidHistoryQuery):
        await store.query("pixel", start=now - timedelta(seconds=1), end=now, metric="raw;SELECT")
    with pytest.raises(InvalidHistoryQuery):
        await store.append(snapshot(now.replace(tzinfo=None), memory()))
    await store.close()


@pytest.mark.parametrize("cursor", ["", "?", "A" * 4097, "e30=", "WzEsW10sW11d"])
async def test_malformed_cursors(cursor: str) -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    start, end = bounds(datetime.now(UTC))
    with pytest.raises(InvalidHistoryQuery):
        await store.query("pixel", start=start, end=end, cursor=cursor)
    await store.close()


async def test_tampered_cursor_invalid_label_is_rejected() -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    now = datetime.now(UTC)
    start, end = bounds(now)
    data = [
        1,
        ["pixel", start.timestamp(), end.timestamp(), None],
        [now.timestamp(), "cpu_core_usage", '{"core":"999"}'],
    ]
    cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(InvalidHistoryQuery):
        await store.query("pixel", start=start, end=end, cursor=cursor)
    await store.close()


async def test_future_and_malformed_schema_are_safe_errors(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=2")
    store = MetricHistoryStore(path)
    with pytest.raises(HistoryError, match="newer"):
        await store.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    malformed = tmp_path / "malformed.db"
    malformed.write_bytes(b"not a SQLite database")
    with pytest.raises(HistoryError):
        await MetricHistoryStore(malformed).initialize()
    await store.close()


async def test_concurrent_initialize_and_append(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    stores = [MetricHistoryStore(path, max_points=2) for _ in range(4)]
    await asyncio.gather(*(store.initialize() for store in stores))
    now = datetime.now(UTC)
    await asyncio.gather(
        *(
            store.append(snapshot(now + timedelta(microseconds=index), memory(index)))
            for index, store in enumerate(stores)
        )
    )
    start, end = bounds(now)
    page = await stores[0].query("pixel", start=start, end=end)
    assert [point.metric.value for point in page.points] == [2, 3]
    await asyncio.gather(*(store.close() for store in stores))


async def test_cancelled_write_drains_before_close() -> None:
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    def write(connection: sqlite3.Connection) -> None:
        entered.set()
        assert release.wait(5)
        with connection:
            connection.execute("PRAGMA user_version=1")
        completed.set()

    worker = asyncio.create_task(store._run(write))
    assert await asyncio.to_thread(entered.wait, 5)
    worker.cancel()
    await asyncio.sleep(0)
    assert not worker.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert completed.is_set()
    await store.close()
    with pytest.raises(HistoryError):
        await store.query(
            "pixel", start=datetime.now(UTC) - timedelta(seconds=1), end=datetime.now(UTC)
        )


async def test_response_models_preserve_units_kinds_labels_and_absence() -> None:
    now = datetime.now(UTC)
    device = Device("pixel", "serial", "Pixel", DeviceState.ONLINE)
    current = current_response(device, None)
    assert current.observed_at is None and current.values == []
    samples = snapshot(now, MetricValue("network_receive", 12, "bytes", (("interface", "wlan0"),)))
    current = current_response(device, samples)
    assert current.values[0].kind == "counter"
    assert current.values[0].labels == {"interface": "wlan0"}
    assert current_response(device, snapshot(now, memory(), device_id="other")).values == []
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    await store.append(samples)
    start, end = bounds(now)
    response = history_response(
        "pixel", start, end, await store.query("pixel", start=start, end=end)
    )
    assert response.points[0].observed_at == now
    assert response.points[0].unit == "bytes"
    await store.close()


async def test_existing_registry_database_is_not_modified(tmp_path: Path) -> None:
    from android_fleet.devices.registry import SQLiteDeviceRegistry

    path = tmp_path / "registry.db"
    registry = SQLiteDeviceRegistry(path)
    await registry.initialize()
    await registry.close()
    with pytest.raises(HistoryError, match="incompatible"):
        await MetricHistoryStore(path).initialize()
    with sqlite3.connect(path) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert tables == [("devices",)]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


async def test_idempotent_memory_lifecycle_and_invalid_constructor() -> None:
    for options in ({"retention_seconds": 0}, {"max_points": 0}, {"max_points": True}):
        with pytest.raises(ValueError):
            MetricHistoryStore(":memory:", **options)
    store = MetricHistoryStore(":memory:")
    await store.initialize()
    await store.initialize()
    await store.close()
    await store.close()
