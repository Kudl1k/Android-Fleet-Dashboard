"""Operator-editable intervals that apply without a restart.

Only scheduling cadences live here. Secrets, ports, paths and limits stay in the
environment: they are read once at start and are never writable through the API.
"""

import asyncio
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    description: str
    minimum: float
    maximum: float


DEFINITIONS: dict[str, SettingDefinition] = {
    item.key: item
    for item in (
        SettingDefinition(
            "metrics_interval_seconds",
            "Telemetry collection interval",
            "How often each online device is sampled. Devices may override it.",
            5,
            3600,
        ),
        SettingDefinition(
            "poll_interval_seconds",
            "Connection check interval",
            "How often registered devices are checked and reconnected.",
            5,
            3600,
        ),
        SettingDefinition(
            "alerts_interval_seconds",
            "Alert evaluation interval",
            "How often alert rules are evaluated against the latest telemetry.",
            2,
            600,
        ),
    )
}
DEVICE_KEYS = frozenset({"metrics_interval_seconds"})


class InvalidSetting(ValueError):
    pass


def _validated(key: str, value: object) -> float:
    definition = DEFINITIONS.get(key)
    if definition is None:
        raise InvalidSetting(f"Unknown setting: {key}")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidSetting(f"{definition.label} must be a number")
    if not definition.minimum <= value <= definition.maximum:
        raise InvalidSetting(
            f"{definition.label} must be between {definition.minimum:g} and "
            f"{definition.maximum:g} seconds"
        )
    return float(value)


class RuntimeSettings:
    """SQLite-backed overrides on top of the environment defaults."""

    def __init__(self, defaults: dict[str, float], path: str | Path | None) -> None:
        unknown = set(defaults) - set(DEFINITIONS)
        if unknown:
            raise InvalidSetting(f"Unknown settings: {sorted(unknown)}")
        self.defaults = dict(defaults)
        self.path = Path(path) if path is not None else None
        self._global: dict[str, float] = {}
        self._devices: dict[str, dict[str, float]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self.path is not None:
            await asyncio.to_thread(self._load)

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute(
            "CREATE TABLE IF NOT EXISTS runtime_settings ("
            "scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at REAL NOT NULL, updated_by TEXT NOT NULL, PRIMARY KEY(scope, key))"
        )
        return db

    def _load(self) -> None:
        with self._connect() as db:
            rows = db.execute("SELECT scope, key, value FROM runtime_settings").fetchall()
        for scope, key, raw in rows:
            try:
                value = _validated(key, json.loads(raw))
            except (InvalidSetting, ValueError):
                continue  # A stale or edited row never breaks start-up.
            if scope == "global":
                self._global[key] = value
            elif scope.startswith("device:") and key in DEVICE_KEYS:
                self._devices.setdefault(scope.removeprefix("device:"), {})[key] = value

    def _store(self, scope: str, key: str, value: float | None, actor: str) -> None:
        if self.path is None:
            return
        with self._connect() as db:
            if value is None:
                db.execute("DELETE FROM runtime_settings WHERE scope=? AND key=?", (scope, key))
            else:
                db.execute(
                    "INSERT INTO runtime_settings(scope,key,value,updated_at,updated_by) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(scope,key) DO UPDATE SET "
                    "value=excluded.value, updated_at=excluded.updated_at, "
                    "updated_by=excluded.updated_by",
                    (scope, key, json.dumps(value), time.time(), actor),
                )

    def value(self, key: str) -> float:
        return self._global.get(key, self.defaults[key])

    def device_value(self, device_id: str, key: str) -> float:
        return self._devices.get(device_id, {}).get(key, self.value(key))

    def device_overrides(self) -> dict[str, dict[str, float]]:
        return {device: dict(values) for device, values in self._devices.items() if values}

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "default": self.defaults[definition.key],
                "value": self.value(definition.key),
                "overridden": definition.key in self._global,
                "per_device": definition.key in DEVICE_KEYS,
            }
            for definition in DEFINITIONS.values()
            if definition.key in self.defaults
        ]

    async def update(self, changes: dict[str, float | None], actor: str) -> None:
        """Set values; None restores the environment default."""
        validated = {
            key: None if value is None else _validated(key, value) for key, value in changes.items()
        }
        missing = set(validated) - set(self.defaults)
        if missing:
            raise InvalidSetting(f"Unknown setting: {sorted(missing)[0]}")
        async with self._lock:
            for key, value in validated.items():
                await asyncio.to_thread(self._store, "global", key, value, actor)
                if value is None:
                    self._global.pop(key, None)
                else:
                    self._global[key] = value

    async def update_device(
        self, device_id: str, changes: dict[str, float | None], actor: str
    ) -> None:
        for key in changes:
            if key not in DEVICE_KEYS:
                raise InvalidSetting(f"{key} cannot be set per device")
        validated = {
            key: None if value is None else _validated(key, value) for key, value in changes.items()
        }
        async with self._lock:
            for key, value in validated.items():
                await asyncio.to_thread(self._store, f"device:{device_id}", key, value, actor)
                values = self._devices.setdefault(device_id, {})
                if value is None:
                    values.pop(key, None)
                else:
                    values[key] = value

    async def forget_device(self, device_id: str, actor: str) -> None:
        await self.update_device(device_id, dict.fromkeys(self._devices.get(device_id, {})), actor)
        self._devices.pop(device_id, None)
