"""Persistent device configuration using a bounded, thread-safe SQLite adapter."""

import asyncio
import ipaddress
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from android_fleet.devices.models import ConnectionType
from android_fleet.devices.registry_models import DeviceRegistration, RegisteredDevice


class RegistryError(Exception):
    """A safe public registry error, without SQL or registration contents."""


class DeviceNotFound(RegistryError):
    pass


class DuplicateDevice(RegistryError):
    pass


class InvalidRegistration(RegistryError):
    pass


_RESULT = TypeVar("_RESULT")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_MDNS = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{0,127})\._adb-tls-connect\._tcp\Z")
_SECRET_KEYS = {"password", "secret", "token", "private_key", "api_key", "pairing_code"}


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise InvalidRegistration("Device ID must be a safe path identifier")
    return value


def _host(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        raise InvalidRegistration("Host must be an IP address or DNS hostname")
    if any(character.isspace() for character in value) or "%" in value:
        raise InvalidRegistration("Host must be an IP address or DNS hostname")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        hostname = value.lower().removesuffix(".")
        if not hostname or not all(_DNS_LABEL.fullmatch(part) for part in hostname.split(".")):
            raise InvalidRegistration("Host must be an IP address or DNS hostname") from None
        return hostname


def normalize_registration(registration: DeviceRegistration) -> DeviceRegistration:
    """Validate at the storage boundary, including callers outside the HTTP API."""
    if not isinstance(registration.connection_type, ConnectionType):
        raise InvalidRegistration("Unsupported connection type")
    if not isinstance(registration.name, str) or not 1 <= len(registration.name.strip()) <= 128:
        raise InvalidRegistration("Name must contain 1 to 128 characters")
    if not isinstance(registration.auto_connect, bool):
        raise InvalidRegistration("Auto-connect must be a boolean")
    host = registration.host
    serial = registration.serial
    service = registration.mdns_service
    if registration.connection_type == ConnectionType.USB:
        if host is not None or registration.port is not None or service is not None:
            raise InvalidRegistration("USB registration requires only a serial")
        if (
            not isinstance(serial, str)
            or not 1 <= len(serial) <= 256
            or any(character.isspace() for character in serial)
            or serial.startswith("-")
        ):
            raise InvalidRegistration("USB serial is invalid")
    else:
        if host is None:
            raise InvalidRegistration("Network registration requires a host and port")
        host = _host(host)
        if (
            not isinstance(registration.port, int)
            or isinstance(registration.port, bool)
            or not 1 <= registration.port <= 65535
        ):
            raise InvalidRegistration("Port must be between 1 and 65535")
        if serial is not None:
            raise InvalidRegistration("Network registration cannot define a USB serial")
        if service is not None:
            if registration.connection_type != ConnectionType.WIRELESS_ADB:
                raise InvalidRegistration("mDNS service requires Wireless ADB")
            if not isinstance(service, str):
                raise InvalidRegistration("Invalid mDNS connection service")
            service = service.removesuffix(".").removesuffix(".local")
            if not _MDNS.fullmatch(service):
                raise InvalidRegistration("Invalid mDNS connection service")
            service = service.lower()
    metadata = registration.metadata
    if not isinstance(metadata, dict) or len(metadata) > 32:
        raise InvalidRegistration("Metadata supports at most 32 string entries")
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 64
            or not isinstance(value, str)
            or len(value) > 1024
        ):
            raise InvalidRegistration("Metadata keys and values must be bounded strings")
        normalized_key = key.lower().replace("-", "_")
        if any(secret in normalized_key for secret in _SECRET_KEYS):
            raise InvalidRegistration("Metadata must not contain credentials")
    return replace(
        registration,
        name=registration.name.strip(),
        host=host,
        mdns_service=service,
        metadata=dict(metadata),
    )


async def _thread_operation[T](operation: Callable[[], T]) -> T:
    """Drain non-cancellable SQLite work before releasing the caller's async lock.

    asyncio.to_thread cancellation does not stop its thread. Shield the worker,
    then defer cancellation (including repeated cancellation) until it finishes.
    A cancelled caller still receives cancellation, even if its transaction fails.
    """
    worker = asyncio.create_task(asyncio.to_thread(operation))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
            if worker.cancelled():
                raise
            continue
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
        if cancelled:
            raise asyncio.CancelledError
        return result


class SQLiteDeviceRegistry:
    """Own one connection, serialized under a lock and used only in worker threads.

    This also supports :memory: without losing data between operations. SQLite's
    unique constraints arbitrate writers from separate adapter instances/processes.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    async def _run(self, operation: Callable[[sqlite3.Connection], _RESULT]) -> _RESULT:
        def locked() -> _RESULT:
            with self._lock:
                if self._connection is None:
                    raise RegistryError("Registry has not been initialized")
                try:
                    return operation(self._connection)
                except sqlite3.IntegrityError:
                    raise DuplicateDevice("Device ID or connection already registered") from None
                except sqlite3.Error:
                    raise RegistryError("Registry operation failed") from None

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
                        raise RegistryError("Registry schema is newer than this application")
                    # Journal-mode changes can return SQLITE_BUSY immediately even
                    # with busy_timeout, when another process initializes this file.
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
                            raise RegistryError("Registry schema is newer than this application")
                        connection.execute(
                            """CREATE TABLE IF NOT EXISTS devices (
                                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                                connection_type TEXT NOT NULL, host TEXT, port INTEGER,
                                serial TEXT UNIQUE, mdns_service TEXT UNIQUE,
                                endpoint TEXT UNIQUE, metadata TEXT NOT NULL,
                                auto_connect INTEGER NOT NULL,
                                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                                last_connected_at TEXT
                            )"""
                        )
                        connection.execute("PRAGMA user_version = 1")
                    self._connection = connection
                except (sqlite3.Error, OSError):
                    if connection is not None:
                        connection.close()
                    raise RegistryError("Could not initialize registry") from None
                except RegistryError:
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

    @staticmethod
    def _decode(row: sqlite3.Row) -> RegisteredDevice:
        metadata: dict[str, str] = json.loads(row["metadata"])
        return RegisteredDevice(
            id=row["id"],
            name=row["name"],
            connection_type=ConnectionType(row["connection_type"]),
            host=row["host"],
            port=row["port"],
            serial=row["serial"],
            mdns_service=row["mdns_service"],
            metadata=metadata,
            auto_connect=bool(row["auto_connect"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_connected_at=(
                datetime.fromisoformat(row["last_connected_at"])
                if row["last_connected_at"] is not None
                else None
            ),
        )

    def _get(self, connection: sqlite3.Connection, device_id: str) -> RegisteredDevice:
        row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise DeviceNotFound("Device is not registered")
        return self._decode(row)

    async def list(self) -> list[RegisteredDevice]:
        return await self._run(
            lambda connection: [
                self._decode(row)
                for row in connection.execute("SELECT * FROM devices ORDER BY created_at, id")
            ]
        )

    async def get(self, device_id: str) -> RegisteredDevice:
        _identifier(device_id)
        return await self._run(lambda connection: self._get(connection, device_id))

    @staticmethod
    def _fields(registration: DeviceRegistration) -> tuple[str | int | None, ...]:
        return (
            registration.name,
            registration.connection_type.value,
            registration.host,
            registration.port,
            registration.serial,
            registration.mdns_service,
            f"{registration.host}|{registration.port}" if registration.host is not None else None,
            json.dumps(registration.metadata, sort_keys=True),
            int(registration.auto_connect),
        )

    async def create(
        self, registration: DeviceRegistration, *, device_id: str | None = None
    ) -> RegisteredDevice:
        normalized = normalize_registration(registration)
        identifier = _identifier(device_id if device_id is not None else str(uuid4()))

        def create_row(connection: sqlite3.Connection) -> RegisteredDevice:
            now = datetime.now(UTC).isoformat()
            with connection:
                connection.execute(
                    """INSERT INTO devices (
                        id, name, connection_type, host, port, serial, mdns_service, endpoint,
                        metadata, auto_connect, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (identifier, *self._fields(normalized), now, now),
                )
                return self._get(connection, identifier)

        return await self._run(create_row)

    async def update(self, device_id: str, registration: DeviceRegistration) -> RegisteredDevice:
        _identifier(device_id)
        normalized = normalize_registration(registration)

        def update_row(connection: sqlite3.Connection) -> RegisteredDevice:
            with connection:
                cursor = connection.execute(
                    """UPDATE devices SET
                        name=?, connection_type=?, host=?, port=?, serial=?, mdns_service=?,
                        endpoint=?, metadata=?, auto_connect=?, updated_at=? WHERE id=?""",
                    (*self._fields(normalized), datetime.now(UTC).isoformat(), device_id),
                )
                if cursor.rowcount == 0:
                    raise DeviceNotFound("Device is not registered")
                return self._get(connection, device_id)

        return await self._run(update_row)

    async def delete(self, device_id: str) -> None:
        _identifier(device_id)

        def delete_row(connection: sqlite3.Connection) -> None:
            with connection:
                cursor = connection.execute("DELETE FROM devices WHERE id=?", (device_id,))
                if cursor.rowcount == 0:
                    raise DeviceNotFound("Device is not registered")

        await self._run(delete_row)

    async def set_auto_connect(self, device_id: str, enabled: bool) -> RegisteredDevice:
        _identifier(device_id)
        if not isinstance(enabled, bool):
            raise InvalidRegistration("Auto-connect must be a boolean")

        def set_enabled(connection: sqlite3.Connection) -> RegisteredDevice:
            with connection:
                cursor = connection.execute(
                    "UPDATE devices SET auto_connect=?, updated_at=? WHERE id=?",
                    (int(enabled), datetime.now(UTC).isoformat(), device_id),
                )
                if cursor.rowcount == 0:
                    raise DeviceNotFound("Device is not registered")
                return self._get(connection, device_id)

        return await self._run(set_enabled)

    async def mark_connected(self, device_id: str, connected_at: datetime) -> None:
        _identifier(device_id)
        if connected_at.tzinfo is None or connected_at.utcoffset() is None:
            raise InvalidRegistration("Connection timestamp must include a timezone")

        def mark(connection: sqlite3.Connection) -> None:
            with connection:
                cursor = connection.execute(
                    "UPDATE devices SET last_connected_at=? WHERE id=?",
                    (connected_at.astimezone(UTC).isoformat(), device_id),
                )
                if cursor.rowcount == 0:
                    raise DeviceNotFound("Device is not registered")

        await self._run(mark)
