"""Backend-owned alert evaluation against normalized fleet observations."""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from android_fleet.alerts.models import AlertState, Condition, Event, Rule, RuleInput, RulePatch
from android_fleet.alerts.store import AlertError, AlertNotFound, AlertStore
from android_fleet.devices.models import DeviceState
from android_fleet.devices.service import FleetService
from android_fleet.metrics.catalog import valid_metric


class AlertEngine:
    def __init__(
        self,
        store: AlertStore,
        fleet: FleetService,
        *,
        max_age_seconds: float,
        retention_seconds: int = 2592000,
    ) -> None:
        self.store = store
        self.fleet = fleet
        self.max_age_seconds = max_age_seconds
        self.healthy = True
        self.retention_seconds = retention_seconds
        self.evaluations_total = 0
        self.evaluation_errors_total = 0
        self.last_evaluation_duration = 0.0
        self.last_evaluation_at: datetime | None = None
        self._last_cleanup = 0.0
        self._lock = asyncio.Lock()
        self._started_at = datetime.now(UTC)
        self._missing_since: dict[str, datetime] = {}
        self._generations: dict[str, int] = {}

    async def initialize(self) -> None:
        await self.store.initialize()
        # Process downtime provides no sustained telemetry evidence. Preserve firing
        # incidents; restart metric pending windows using the next fresh observation.
        now = datetime.now(UTC)
        for event in await self.store.active():
            if event.state == AlertState.PENDING and event.condition != Condition.OFFLINE:
                event.state = AlertState.RESOLVED
                event.resolved_at = now
                event.updated_at = now
                await self.store.save_event(event)
        self._generations = {
            device_id: self.fleet.observation_generation(device_id)
            for device_id in self.fleet.devices
        }
        if not await self.store.defaults_seeded():
            defaults = [
                (Condition.BATTERY_LOW, 0.15, 0.03),
                (Condition.BATTERY_TEMPERATURE, 45, 3),
                (Condition.DEVICE_TEMPERATURE, 70, 5),
                (Condition.CPU_HIGH, 0.9, 0.05),
                (Condition.MEMORY_HIGH, 0.9, 0.05),
                (Condition.STORAGE_LOW, 0.1, 0.03),
                (Condition.OFFLINE, 120, 0),
                (Condition.TELEMETRY_STALE, 120, 0),
            ]
            for condition, threshold, hysteresis in defaults:
                await self.store.save_rule(
                    Rule(
                        id=f"default-{condition}",
                        name=condition.value.replace("_", " ").title(),
                        condition=condition,
                        threshold=threshold,
                        hysteresis=hysteresis,
                    )
                )

            await self.store.mark_defaults_seeded()

    def _value(self, rule: Rule, device_id: str, now: datetime) -> float | None:
        device = self.fleet.devices.get(device_id)
        if device is None:
            return None
        if rule.condition == Condition.OFFLINE:
            if device.state == DeviceState.ONLINE:
                return 0
            since = device.last_seen or self._started_at
            return max(0, (now - since).total_seconds())
        snapshot = self.fleet.snapshots.get(device_id)
        valid_values = (
            [value for value in snapshot.values if valid_metric(value)] if snapshot else []
        )
        if rule.condition == Condition.TELEMETRY_STALE:
            # Offline has its own rule; stale telemetry represents an online collector issue.
            if device.state != DeviceState.ONLINE:
                self._missing_since.pop(device_id, None)
                return 0
            if snapshot is not None and valid_values:
                self._missing_since.pop(device_id, None)
                since = snapshot.observed_at
            else:
                since = self._missing_since.setdefault(device_id, now)

            return max(0, (now - since).total_seconds())
        if device.state != DeviceState.ONLINE or snapshot is None:
            return None
        age = (now - snapshot.observed_at).total_seconds()
        if age < 0 or age > self.max_age_seconds:
            return None
        values = {value.name: value.value for value in valid_values if not value.labels}
        metric = {
            Condition.BATTERY_LOW: "battery_level",
            Condition.BATTERY_TEMPERATURE: "battery_temperature",
            Condition.CPU_HIGH: "cpu_usage",
        }.get(rule.condition)
        if metric:
            return values.get(metric)
        if rule.condition == Condition.DEVICE_TEMPERATURE:
            temperatures = [
                value.value for value in valid_values if value.name == "thermal_temperature"
            ]
            return max(temperatures) if temperatures else None
        if rule.condition == Condition.MEMORY_HIGH:
            total, used = values.get("memory_total"), values.get("memory_used")
            return used / total if total and used is not None else None
        if rule.condition == Condition.STORAGE_LOW:
            storage = {
                value.name: value.value
                for value in valid_values
                if dict(value.labels).get("mount") == "/data"
            }
            total, free = storage.get("storage_total"), storage.get("storage_free")
            return free / total if total and free is not None else None
        return None

    async def evaluate(self, now: datetime | None = None) -> None:
        timestamp = now or datetime.now(UTC)
        async with self._lock:
            rules = await self.store.rules()
            active = {
                (event.rule_id, event.device_id): event for event in await self.store.active()
            }
            overrides = {(rule.device_id, rule.condition) for rule in rules if rule.device_id}
            self._missing_since = {
                key: value
                for key, value in self._missing_since.items()
                if key in self.fleet.devices and self.fleet.devices[key].state == DeviceState.ONLINE
            }
            generations = {
                device_id: self.fleet.observation_generation(device_id)
                for device_id in self.fleet.devices
            }
            changed = {
                device_id
                for device_id, generation in generations.items()
                if device_id in self._generations and self._generations[device_id] != generation
            }
            for device_id in changed:
                self._missing_since.pop(device_id, None)
            self._generations = generations
            effective: set[tuple[str, str]] = set()
            for rule in rules:
                if not rule.enabled:
                    continue
                for device_id, device in list(self.fleet.devices.items()):
                    if rule.device_id is not None and rule.device_id != device_id:
                        continue
                    if rule.device_id is None and (device_id, rule.condition) in overrides:
                        continue
                    key = (rule.id, device_id)
                    effective.add(key)
                    event = active.get(key)
                    if (
                        event is not None
                        and event.state == AlertState.PENDING
                        and device_id in changed
                        and rule.condition != Condition.OFFLINE
                    ):
                        event.state = AlertState.RESOLVED
                        event.resolved_at = timestamp
                        event.updated_at = timestamp
                        await self.store.save_event(event)
                        event = None
                    value = self._value(rule, device_id, timestamp)
                    low = rule.condition in {Condition.BATTERY_LOW, Condition.STORAGE_LOW}
                    violated = value is not None and (
                        value < rule.threshold if low else value > rule.threshold
                    )
                    recovered = value is not None and (
                        value >= rule.threshold + rule.hysteresis
                        if low
                        else value <= rule.threshold - rule.hysteresis
                    )
                    if event is None and violated:
                        event = Event(
                            id=str(uuid4()),
                            rule_id=rule.id,
                            device_id=device_id,
                            device_name=device.name,
                            condition=rule.condition,
                            severity=rule.severity,
                            threshold=rule.threshold,
                            value=value,
                            state=AlertState.PENDING,
                            started_at=timestamp,
                            updated_at=timestamp,
                        )
                    if event is None:
                        continue
                    # Unknown observations break a pending sustained condition, but never
                    # claim an existing firing condition recovered without evidence.
                    if recovered or (event.state == AlertState.PENDING and not violated):
                        event.state = AlertState.RESOLVED
                        event.resolved_at = timestamp
                    elif (
                        event.state == AlertState.PENDING
                        and violated
                        and (timestamp - event.started_at).total_seconds() >= rule.duration_seconds
                    ):
                        event.state = AlertState.FIRING
                        event.fired_at = timestamp
                    event.updated_at = timestamp
                    event.value = value
                    await self.store.save_event(event)
            for key, event in active.items():
                if key not in effective:
                    event.state = AlertState.RESOLVED
                    event.resolved_at = timestamp
                    event.updated_at = timestamp
                    await self.store.save_event(event)

    async def run(self, interval: float | Callable[[], float]) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.evaluate()
                if time.monotonic() - self._last_cleanup >= 60:
                    await self.store.cleanup(self.retention_seconds)
                    self._last_cleanup = time.monotonic()
            except AlertError:
                self.healthy = False
                self.evaluation_errors_total += 1
            else:
                self.healthy = True
            self.evaluations_total += 1
            self.last_evaluation_duration = time.monotonic() - started
            self.last_evaluation_at = datetime.now(UTC)
            await asyncio.sleep(interval() if callable(interval) else interval)

    async def save_rule(self, body: RuleInput, rule_id: str | None = None) -> Rule:
        async with self._lock:
            return await self._save_rule(body, rule_id)

    async def _save_rule(self, body: RuleInput, rule_id: str | None) -> Rule:
        if rule_id is not None and not any(r.id == rule_id for r in await self.store.rules()):
            raise AlertNotFound("Alert rule not found")
        # Exactly one global/default or per-device rule for each condition.
        for current in await self.store.rules():
            if current.id != rule_id and (current.device_id, current.condition) == (
                body.device_id,
                body.condition,
            ):
                raise ValueError("A rule for this device and condition already exists")
        if rule_id is not None:
            now = datetime.now(UTC)
            for event in await self.store.active():
                if event.rule_id == rule_id:
                    event.state = AlertState.RESOLVED
                    event.resolved_at = now
                    event.updated_at = now
                    await self.store.save_event(event)
        rule = Rule(id=rule_id or str(uuid4()), **body.model_dump())
        await self.store.save_rule(rule)
        return rule

    async def patch_rule(self, rule_id: str, body: RulePatch) -> Rule:
        async with self._lock:
            current = next((r for r in await self.store.rules() if r.id == rule_id), None)
            if current is None:
                raise AlertNotFound("Alert rule not found")
            fields = current.model_dump(exclude={"id"})
            fields.update(body.model_dump(exclude_unset=True))
            return await self._save_rule(RuleInput.model_validate(fields), rule_id)

    async def delete_rule(self, rule_id: str) -> None:
        async with self._lock:
            await self.store.delete_rule(rule_id)
        await self.evaluate()

    async def acknowledge(self, event_id: str) -> Event:
        async with self._lock:
            event = await self.store.event(event_id)
            if event.state not in {AlertState.FIRING, AlertState.ACKNOWLEDGED}:
                raise ValueError("Only firing alerts can be acknowledged")
            if event.state != AlertState.ACKNOWLEDGED:
                event.state = AlertState.ACKNOWLEDGED
                event.acknowledged_at = datetime.now(UTC)
                event.updated_at = event.acknowledged_at
                await self.store.save_event(event)
            return event
