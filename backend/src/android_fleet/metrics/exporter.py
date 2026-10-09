"""Prometheus names, bounded labels and freshness belong to the export boundary."""

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from android_fleet.devices.models import Device, DeviceState
from android_fleet.metrics.catalog import DEFINITIONS, MetricKind, valid_metric
from android_fleet.metrics.models import MetricSnapshot

# Explicit vocabulary: unrecognized domain values cannot create Prometheus names.
METRICS = {
    "battery_level": "android_battery_level_ratio",
    "battery_temperature": "android_battery_temperature_celsius",
    "battery_voltage": "android_battery_voltage_volts",
    "battery_current": "android_battery_current_amperes",
    "battery_status": "android_battery_status",
    "battery_health": "android_battery_health",
    "battery_charging": "android_battery_charging",
    "cpu_usage": "android_cpu_usage_ratio",
    "cpu_core_usage": "android_cpu_core_usage_ratio",
    "cpu_frequency": "android_cpu_frequency_hz",
    "memory_total": "android_memory_total_bytes",
    "memory_available": "android_memory_available_bytes",
    "memory_used": "android_memory_used_bytes",
    "swap_used": "android_swap_used_bytes",
    "storage_total": "android_storage_total_bytes",
    "storage_used": "android_storage_used_bytes",
    "storage_free": "android_storage_free_bytes",
    "network_receive": "android_network_receive_bytes_total",
    "network_transmit": "android_network_transmit_bytes_total",
    "uptime": "android_uptime_seconds",
    "thermal_temperature": "android_temperature_celsius",
    "thermal_status": "android_thermal_status",
}


class FleetExporter:
    def __init__(
        self,
        devices: Sequence[Device],
        snapshots: Mapping[str, MetricSnapshot],
        *,
        max_age_seconds: float = 120,
        now: datetime | None = None,
    ) -> None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive")
        self.devices = devices
        self.snapshots = snapshots
        self.max_age_seconds = max_age_seconds
        self.now = now or datetime.now(UTC)

    def collect(self) -> Iterable[GaugeMetricFamily | CounterMetricFamily]:
        up = GaugeMetricFamily("android_device_up", "Online ADB transport.", labels=["device_id"])
        rooted = GaugeMetricFamily(
            "android_device_rooted", "Observed root availability.", labels=["device_id"]
        )
        seen = GaugeMetricFamily(
            "android_device_last_seen_timestamp_seconds",
            "Last successful device observation, Unix seconds.",
            labels=["device_id"],
        )
        collected = GaugeMetricFamily(
            "android_metrics_last_collection_timestamp_seconds",
            "Fresh metric snapshot observation, Unix seconds.",
            labels=["device_id"],
        )
        families: dict[str, GaugeMetricFamily | CounterMetricFamily] = {}
        for key, name in METRICS.items():
            definition = DEFINITIONS[key]
            family = (
                CounterMetricFamily if definition.kind == MetricKind.COUNTER else GaugeMetricFamily
            )
            families[key] = family(
                name, f"Observed {key.replace('_', ' ')}.", labels=["device_id", *definition.labels]
            )
        for device in self.devices:
            up.add_metric([device.id], float(device.state == DeviceState.ONLINE))
            if device.last_seen is not None:
                seen.add_metric([device.id], device.last_seen.timestamp())
            if device.state != DeviceState.ONLINE:
                continue
            if device.root_available is not None:
                rooted.add_metric([device.id], float(device.root_available))
            snapshot = self.snapshots.get(device.id)
            if snapshot is None or snapshot.device_id != device.id:
                continue
            if snapshot.observed_at.tzinfo is None:
                continue
            age = (self.now - snapshot.observed_at).total_seconds()
            if age < 0 or age > self.max_age_seconds:
                continue
            collected.add_metric([device.id], snapshot.observed_at.timestamp())
            identities: set[tuple[str, tuple[str, ...]]] = set()
            dimensions: dict[str, set[str]] = {"interface": set(), "sensor": set(), "core": set()}
            for value in snapshot.values:
                if value.name not in families or not valid_metric(value):
                    continue
                definition = DEFINITIONS[value.name]
                labels = dict(value.labels)
                label_values = tuple(labels[key] for key in definition.labels)
                identity = (value.name, label_values)
                if identity in identities:
                    continue
                limits = {"interface": 32, "sensor": 32, "core": 256}
                if any(
                    label not in dimensions[key] and len(dimensions[key]) >= limits[key]
                    for key, label in labels.items()
                    if key in dimensions
                ):
                    continue
                for key, label in labels.items():
                    if key in dimensions:
                        dimensions[key].add(label)
                identities.add(identity)
                families[value.name].add_metric([device.id, *label_values], value.value)
        yield up
        yield rooted
        yield seen
        yield collected
        yield from families.values()


def render_metrics(
    devices: Sequence[Device],
    snapshots: Mapping[str, MetricSnapshot],
    *,
    max_age_seconds: float = 120,
    now: datetime | None = None,
) -> bytes:
    registry = CollectorRegistry()
    registry.register(FleetExporter(devices, snapshots, max_age_seconds=max_age_seconds, now=now))
    return generate_latest(registry)
