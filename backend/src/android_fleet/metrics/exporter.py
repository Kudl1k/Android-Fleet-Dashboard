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
    "battery_charge": "android_battery_charge_ampere_hours",
    "battery_charge_full": "android_battery_charge_full_ampere_hours",
    "battery_charge_full_design": "android_battery_charge_full_design_ampere_hours",
    "battery_cycle_count": "android_battery_cycle_count",
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
    "cpu_max_frequency": "android_cpu_max_frequency_hz",
    "cpu_frequency_limit": "android_cpu_frequency_limit_hz",
    "cpu_frequency_capped": "android_cpu_frequency_capped",
    "zram_disk_size": "android_zram_disk_size_bytes",
    "zram_original_data": "android_zram_original_data_bytes",
    "zram_compressed_data": "android_zram_compressed_data_bytes",
    "zram_memory_used": "android_zram_memory_used_bytes",
    "gpu_usage": "android_gpu_usage_ratio",
    "gpu_frequency": "android_gpu_frequency_hz",
    "gpu_max_frequency": "android_gpu_max_frequency_hz",
    "process_count": "android_process_count",
    "process_cpu": "android_process_cpu_ratio",
    "process_memory": "android_process_memory_bytes",
}
INFO_LABELS = ("manufacturer", "model", "android_version", "soc", "kernel")
_LIMITS = {"interface": 32, "sensor": 32, "core": 256, "process": 16}


def _info_value(value: str | None) -> str:
    # Free-form properties become bounded printable label values, never label names.
    text = "".join(c if c.isprintable() else "_" for c in (value or "").strip())
    return text[:64]


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
        info = GaugeMetricFamily(
            "android_device_info",
            "Probed device identity; value is always 1.",
            labels=["device_id", *INFO_LABELS],
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
            identity_fields = tuple(_info_value(getattr(device, key)) for key in INFO_LABELS)
            if any(identity_fields):
                info.add_metric([device.id, *identity_fields], 1)
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
            dimensions: dict[str, set[str]] = {key: set() for key in _LIMITS}
            for value in snapshot.values:
                if value.name not in families or not valid_metric(value):
                    continue
                definition = DEFINITIONS[value.name]
                labels = dict(value.labels)
                label_values = tuple(labels[key] for key in definition.labels)
                identity = (value.name, label_values)
                if identity in identities:
                    continue
                if any(
                    label not in dimensions[key] and len(dimensions[key]) >= _LIMITS[key]
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
        yield info
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
