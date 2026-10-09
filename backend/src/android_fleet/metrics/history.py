"""Bounded local metric history, independent of HTTP and Prometheus."""

import base64
import binascii
import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from android_fleet.devices.registry import _thread_operation
from android_fleet.metrics.catalog import DEFINITIONS, valid_metric
from android_fleet.metrics.models import HistoricalPoint, HistoryPage, MetricSnapshot, MetricValue


class HistoryError(Exception):
    """Safe public persistence failure; no SQL or metric contents."""


class InvalidHistoryQuery(HistoryError):
    pass


def _timestamp(value: datetime) -> float:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidHistoryQuery("Timestamps must include a timezone")
    return value.timestamp()


def _device_id(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise InvalidHistoryQuery("Device identifier is invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise InvalidHistoryQuery("Device identifier is invalid")


def _labels(value: MetricValue) -> str:
    return json.dumps(dict(value.labels), sort_keys=True, separators=(",", ":"))


class MetricHistoryStore:
    """One locked SQLite connection; all I/O happens in cancellation-drained threads.

    Retention is enforced on writes and reads. A trigger-maintained row count makes
    capacity checks constant-time; indexed eviction removes only excess rows.
    The file may retain allocated pages up to its historical capacity high-water mark.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        retention_seconds: int = 604800,
        max_points: int = 1_000_000,
    ) -> None:
        if (
            not isinstance(retention_seconds, int)
            or isinstance(retention_seconds, bool)
            or retention_seconds <= 0
            or not isinstance(max_points, int)
            or isinstance(max_points, bool)
            or max_points <= 0
        ):
            raise ValueError("History retention and capacity must be positive integers")
        self.path = str(path)
        self.retention_seconds = retention_seconds
        self.max_points = max_points
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    async def _run[T](self, operation: Callable[[sqlite3.Connection], T]) -> T:
        def locked() -> T:
            with self._lock:
                if self._connection is None:
                    raise HistoryError("History store has not been initialized")
                try:
                    return operation(self._connection)
                except sqlite3.Error:
                    raise HistoryError("History operation failed") from None

        return await _thread_operation(locked)

    async def initialize(self) -> None:
        def initialize_connection() -> None:
            with self._lock:
                if self._connection is not None:
                    return
                connection: sqlite3.Connection | None = None
                try:
                    if self.path != ":memory:":
                        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                    connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
                    connection.row_factory = sqlite3.Row
                    connection.execute("PRAGMA busy_timeout = 5000")
                    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    if version > 1:
                        raise HistoryError("History schema is newer than this application")
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' "
                            "AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    if tables and tables != {"samples", "history_stats"}:
                        raise HistoryError("History database schema is incompatible")
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            connection.execute("PRAGMA journal_mode = WAL")
                            break
                        except sqlite3.OperationalError as error:
                            if (
                                error.sqlite_errorcode & 0xFF
                                not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                                or time.monotonic() >= deadline
                            ):
                                raise
                            time.sleep(0.01)
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                        if version > 1:
                            raise HistoryError("History schema is newer than this application")
                        tables = {
                            row[0]
                            for row in connection.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%'"
                            )
                        }
                        if (version == 0 and tables) or (
                            version == 1 and tables != {"samples", "history_stats"}
                        ):
                            raise HistoryError("History database schema is incompatible")
                        connection.execute(
                            """CREATE TABLE IF NOT EXISTS samples (
                                device_id TEXT NOT NULL, observed_at REAL NOT NULL,
                                name TEXT NOT NULL, labels TEXT NOT NULL,
                                value REAL NOT NULL, unit TEXT NOT NULL,
                                PRIMARY KEY (device_id, observed_at, name, labels)
                            )"""
                        )
                        connection.execute(
                            "CREATE INDEX IF NOT EXISTS samples_metric_time "
                            "ON samples(device_id, name, observed_at, labels)"
                        )
                        connection.execute(
                            "CREATE INDEX IF NOT EXISTS samples_eviction "
                            "ON samples(observed_at, device_id, name, labels)"
                        )
                        connection.execute(
                            "CREATE TABLE IF NOT EXISTS history_stats "
                            "(id INTEGER PRIMARY KEY CHECK(id=1), point_count INTEGER NOT NULL)"
                        )
                        connection.execute(
                            "INSERT OR IGNORE INTO history_stats SELECT 1, COUNT(*) FROM samples"
                        )
                        connection.execute(
                            """CREATE TRIGGER IF NOT EXISTS history_insert AFTER INSERT ON samples
                            BEGIN UPDATE history_stats SET point_count=point_count+1 WHERE id=1;
                            END"""
                        )
                        connection.execute(
                            """CREATE TRIGGER IF NOT EXISTS history_delete AFTER DELETE ON samples
                            BEGIN UPDATE history_stats SET point_count=point_count-1 WHERE id=1;
                            END"""
                        )
                        connection.execute("PRAGMA user_version = 1")
                        self._prune(connection, time.time())
                    self._connection = connection
                except (sqlite3.Error, OSError):
                    if connection is not None:
                        connection.close()
                    raise HistoryError("Could not initialize history store") from None
                except HistoryError:
                    if connection is not None:
                        connection.close()
                    raise

        await _thread_operation(initialize_connection)

    async def close(self) -> None:
        def close_connection() -> None:
            with self._lock:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None

        await _thread_operation(close_connection)

    def _prune(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM samples WHERE observed_at < ?", (now - self.retention_seconds,)
        )
        count = int(
            connection.execute("SELECT point_count FROM history_stats WHERE id=1").fetchone()[0]
        )
        if count > self.max_points:
            connection.execute(
                "DELETE FROM samples WHERE rowid IN ("
                "SELECT rowid FROM samples ORDER BY observed_at, device_id, name, labels LIMIT ?)",
                (count - self.max_points,),
            )

    async def append(self, snapshot: MetricSnapshot) -> None:
        _device_id(snapshot.device_id)
        timestamp = _timestamp(snapshot.observed_at)
        values = {
            (value.name, _labels(value)): value for value in snapshot.values if valid_metric(value)
        }

        def append_values(connection: sqlite3.Connection) -> None:
            now = time.time()
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if timestamp >= now - self.retention_seconds:
                    connection.executemany(
                        """INSERT INTO samples(device_id, observed_at, name, labels, value, unit)
                        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(device_id,observed_at,name,labels)
                        DO UPDATE SET value=excluded.value, unit=excluded.unit""",
                        [
                            (snapshot.device_id, timestamp, name, labels, value.value, value.unit)
                            for (name, labels), value in values.items()
                        ],
                    )
                self._prune(connection, now)

        await self._run(append_values)

    async def prune(self) -> None:
        def prune_values(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                self._prune(connection, time.time())

        await self._run(prune_values)

    async def delete_device(self, device_id: str) -> None:
        _device_id(device_id)

        def delete_values(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute("DELETE FROM samples WHERE device_id=?", (device_id,))

        await self._run(delete_values)

    @staticmethod
    def _cursor(identity: list[str | float | None], row: sqlite3.Row) -> str:
        data = [1, identity, [row["observed_at"], row["name"], row["labels"]]]
        return base64.urlsafe_b64encode(
            json.dumps(data, separators=(",", ":")).encode("ascii")
        ).decode("ascii")

    @staticmethod
    def _decode_cursor(
        cursor: str, identity: list[str | float | None], start: float, end: float
    ) -> tuple[float, str, str]:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
                raise ValueError
            raw = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
            data = json.loads(raw)
            if (
                not isinstance(data, list)
                or len(data) != 3
                or type(data[0]) is not int
                or data[0] != 1
                or data[1] != identity
            ):
                raise ValueError
            key = data[2]
            if (
                not isinstance(key, list)
                or len(key) != 3
                or not isinstance(key[0], (int, float))
                or isinstance(key[0], bool)
                or not math.isfinite(key[0])
                or not start <= key[0] < end
                or not isinstance(key[1], str)
                or key[1] not in DEFINITIONS
                or not isinstance(key[2], str)
                or len(key[2]) > 1024
            ):
                raise ValueError
            labels = json.loads(key[2])
            if not isinstance(labels, dict) or not all(
                isinstance(name, str) and isinstance(value, str) for name, value in labels.items()
            ):
                raise ValueError
            definition = DEFINITIONS[key[1]]
            if set(labels) != set(definition.labels) or not valid_metric(
                MetricValue(key[1], 0, definition.unit, tuple(sorted(labels.items())))
            ):
                raise ValueError
            canonical = json.dumps(labels, sort_keys=True, separators=(",", ":"))
            if canonical != key[2] or (identity[3] is not None and key[1] != identity[3]):
                raise ValueError
            return float(key[0]), key[1], key[2]
        except (ValueError, TypeError, OverflowError, UnicodeError, binascii.Error, RecursionError):
            raise InvalidHistoryQuery("History cursor is invalid for this query") from None

    async def query(
        self,
        device_id: str,
        *,
        start: datetime,
        end: datetime,
        metric: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> HistoryPage:
        _device_id(device_id)
        first, last = _timestamp(start), _timestamp(end)
        if not first < last or last - first > self.retention_seconds:
            raise InvalidHistoryQuery("Query range must be ordered and within history retention")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10000:
            raise InvalidHistoryQuery("History limit must be between 1 and 10000")
        if metric is not None and (not isinstance(metric, str) or metric not in DEFINITIONS):
            raise InvalidHistoryQuery("Unknown metric name")
        identity: list[str | float | None] = [device_id, first, last, metric]
        key = self._decode_cursor(cursor, identity, first, last) if cursor is not None else None

        def query_values(connection: sqlite3.Connection) -> HistoryPage:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                now = time.time()
                self._prune(connection, now)
                conditions = ["device_id=?", "observed_at>=?", "observed_at<?"]
                parameters: list[str | float | int] = [
                    device_id,
                    max(first, now - self.retention_seconds),
                    last,
                ]
                if metric is not None:
                    conditions.append("name=?")
                    parameters.append(metric)
                if key is not None:
                    conditions.append("(observed_at,name,labels)>(?,?,?)")
                    parameters.extend(key)
                parameters.append(limit + 1)
                rows = connection.execute(
                    "SELECT observed_at,name,labels,value,unit FROM samples WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY observed_at,name,labels LIMIT ?",
                    parameters,
                ).fetchall()
                selected = rows[:limit]
                try:
                    points = tuple(
                        HistoricalPoint(
                            datetime.fromtimestamp(row["observed_at"], UTC),
                            MetricValue(
                                row["name"],
                                row["value"],
                                row["unit"],
                                tuple(sorted(json.loads(row["labels"]).items())),
                            ),
                        )
                        for row in selected
                    )
                    if any(not valid_metric(point.metric) for point in points):
                        raise ValueError
                except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
                    raise HistoryError("Stored history contains invalid observations") from None
                return HistoryPage(
                    points, self._cursor(identity, selected[-1]) if len(rows) > limit else None
                )

        return await self._run(query_values)
