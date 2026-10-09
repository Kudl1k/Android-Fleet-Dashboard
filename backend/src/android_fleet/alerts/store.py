"""Versioned SQLite persistence with cancellation-drained off-thread operations."""

import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from android_fleet.alerts.models import Event, Rule
from android_fleet.devices.registry import _thread_operation


class AlertError(RuntimeError):
    pass


class AlertNotFound(AlertError):
    pass


class AlertStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    async def _run[T](self, operation: Callable[[sqlite3.Connection], T]) -> T:
        def locked() -> T:
            with self._lock:
                if self._connection is None:
                    raise AlertError("Alert storage is unavailable")
                try:
                    return operation(self._connection)
                except sqlite3.Error:
                    raise AlertError("Alert persistence failed") from None

        return await _thread_operation(locked)

    async def initialize(self) -> None:
        def initialize() -> None:
            with self._lock:
                if self._connection is not None:
                    return
                if self.path != ":memory:":
                    Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
                try:
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version > 1:
                        raise AlertError("Alert schema is newer than this application")
                    connection.executescript("""
                        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY);
                        CREATE TABLE IF NOT EXISTS rules (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS events (
                          id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, device_id TEXT NOT NULL,
                          state TEXT NOT NULL, severity TEXT NOT NULL, started_at TEXT NOT NULL,
                          body TEXT NOT NULL);
                        CREATE UNIQUE INDEX IF NOT EXISTS active_event ON events(rule_id,device_id)
                          WHERE state != 'resolved';
                        CREATE INDEX IF NOT EXISTS event_history ON events(started_at DESC);
                        PRAGMA user_version = 1;
                    """)
                    connection.commit()
                    self._connection = connection
                except BaseException:
                    connection.close()
                    raise

        await _thread_operation(initialize)

    async def close(self) -> None:
        def close() -> None:
            with self._lock:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None

        await _thread_operation(close)

    async def rules(self) -> list[Rule]:
        return await self._run(
            lambda db: [
                Rule.model_validate_json(row[0])
                for row in db.execute("SELECT body FROM rules ORDER BY id")
            ]
        )

    async def save_rule(self, rule: Rule) -> None:
        def save(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT OR REPLACE INTO rules VALUES (?,?)", (rule.id, rule.model_dump_json())
            )
            db.commit()

        await self._run(save)

    async def delete_rule(self, rule_id: str) -> None:
        def delete(db: sqlite3.Connection) -> None:
            if db.execute("DELETE FROM rules WHERE id=?", (rule_id,)).rowcount == 0:
                raise AlertNotFound("Alert rule not found")
            db.commit()

        await self._run(delete)

    async def save_event(self, event: Event) -> None:
        def save(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)",
                (
                    event.id,
                    event.rule_id,
                    event.device_id,
                    event.state,
                    event.severity,
                    event.started_at.isoformat(),
                    event.model_dump_json(),
                ),
            )
            db.commit()

        await self._run(save)

    async def events(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Event], int]:
        def query(db: sqlite3.Connection) -> tuple[list[Event], int]:
            filters = {"state": state, "severity": severity, "device_id": device_id}
            selected = [(key, value) for key, value in filters.items() if value is not None]
            where = " WHERE " + " AND ".join(f"{key}=?" for key, _ in selected) if selected else ""
            params = [value for _, value in selected]
            count = int(db.execute("SELECT count(*) FROM events" + where, params).fetchone()[0])
            rows = db.execute(
                "SELECT body FROM events"
                + where
                + " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
            return [Event.model_validate_json(row[0]) for row in rows], count

        return await self._run(query)

    async def active(self) -> list[Event]:
        return await self._run(
            lambda db: [
                Event.model_validate_json(row[0])
                for row in db.execute("SELECT body FROM events WHERE state != 'resolved'")
            ]
        )

    async def event(self, event_id: str) -> Event:
        def get(db: sqlite3.Connection) -> Event:
            row = db.execute("SELECT body FROM events WHERE id=?", (event_id,)).fetchone()
            if row is None:
                raise AlertNotFound("Alert not found")
            return Event.model_validate(json.loads(row[0]))

        return await self._run(get)

    async def defaults_seeded(self) -> bool:
        return await self._run(
            lambda db: (
                db.execute("SELECT 1 FROM metadata WHERE key='defaults_seeded'").fetchone()
                is not None
            )
        )

    async def mark_defaults_seeded(self) -> None:
        def mark(db: sqlite3.Connection) -> None:
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('defaults_seeded')")
            db.commit()

        await self._run(mark)

    async def cleanup(self, retention_seconds: int, *, now: datetime | None = None) -> int:
        """Expire only resolved incidents; active lifecycle evidence is retained."""
        cutoff = (now or datetime.now(UTC)) - timedelta(seconds=retention_seconds)

        def remove(db: sqlite3.Connection) -> int:
            rows = db.execute("SELECT id, body FROM events WHERE state='resolved'").fetchall()
            expired = []
            for identifier, body in rows:
                event = Event.model_validate_json(body)
                if (event.resolved_at or event.updated_at) < cutoff:
                    expired.append(identifier)
            db.executemany(
                "DELETE FROM events WHERE id=?", [(identifier,) for identifier in expired]
            )
            db.commit()
            return len(expired)

        return await self._run(remove)
