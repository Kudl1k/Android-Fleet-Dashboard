"""Domain metric vocabulary and bounded dimensions; no monitoring transport names."""

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from android_fleet.metrics.models import MetricValue


class MetricKind(StrEnum):
    GAUGE = "gauge"
    COUNTER = "counter"


@dataclass(frozen=True)
class MetricDefinition:
    unit: str
    kind: MetricKind = MetricKind.GAUGE
    labels: tuple[str, ...] = ()
    minimum: float | None = 0
    maximum: float | None = None


DEFINITIONS: dict[str, MetricDefinition] = {
    "battery_level": MetricDefinition("ratio", maximum=1),
    "battery_temperature": MetricDefinition("celsius", minimum=-40, maximum=200),
    "battery_voltage": MetricDefinition("volts", maximum=30),
    "battery_current": MetricDefinition("amperes", minimum=-100, maximum=100),
    "battery_status": MetricDefinition("level", minimum=1, maximum=5),
    "battery_health": MetricDefinition("level", minimum=1, maximum=7),
    "battery_charging": MetricDefinition("boolean", maximum=1),
    "battery_charge": MetricDefinition("ampere_hours", maximum=100),
    "battery_charge_full": MetricDefinition("ampere_hours", maximum=100),
    "battery_charge_full_design": MetricDefinition("ampere_hours", maximum=100),
    "battery_cycle_count": MetricDefinition("count", maximum=100_000),
    "cpu_usage": MetricDefinition("ratio", maximum=1),
    "cpu_core_usage": MetricDefinition("ratio", labels=("core",), maximum=1),
    "cpu_frequency": MetricDefinition("hertz", labels=("core",)),
    "memory_total": MetricDefinition("bytes"),
    "memory_available": MetricDefinition("bytes"),
    "memory_used": MetricDefinition("bytes"),
    "swap_used": MetricDefinition("bytes"),
    "storage_total": MetricDefinition("bytes", labels=("mount",)),
    "storage_used": MetricDefinition("bytes", labels=("mount",)),
    "storage_free": MetricDefinition("bytes", labels=("mount",)),
    "network_receive": MetricDefinition("bytes", MetricKind.COUNTER, ("interface",)),
    "network_transmit": MetricDefinition("bytes", MetricKind.COUNTER, ("interface",)),
    "uptime": MetricDefinition("seconds"),
    "thermal_temperature": MetricDefinition(
        "celsius", labels=("sensor", "type"), minimum=-40, maximum=200
    ),
    "thermal_status": MetricDefinition("level", maximum=6),
    "cpu_max_frequency": MetricDefinition("hertz", labels=("core",)),
    "cpu_frequency_limit": MetricDefinition("hertz", labels=("core",)),
    "cpu_frequency_capped": MetricDefinition("boolean", maximum=1),
    "zram_disk_size": MetricDefinition("bytes"),
    "zram_original_data": MetricDefinition("bytes"),
    "zram_compressed_data": MetricDefinition("bytes"),
    "zram_memory_used": MetricDefinition("bytes"),
    "npu_frequency": MetricDefinition("hertz", labels=("accelerator",)),
    "gpu_usage": MetricDefinition("ratio", maximum=1),
    "gpu_frequency": MetricDefinition("hertz"),
    "gpu_max_frequency": MetricDefinition("hertz"),
    "process_count": MetricDefinition("count", maximum=1_000_000),
    "process_cpu": MetricDefinition("ratio", labels=("process",), maximum=256),
    "process_memory": MetricDefinition("bytes", labels=("process",)),
}

_INTEGER_METRICS = {
    "thermal_status",
    "battery_status",
    "battery_health",
    "battery_charging",
    "battery_cycle_count",
    "cpu_frequency_capped",
    "process_count",
}
_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_THERMAL_TYPES = {"cpu", "gpu", "battery", "skin", "usb", "power_amplifier", "npu", "unknown"}


def valid_metric(value: MetricValue) -> bool:
    definition = DEFINITIONS.get(value.name)
    if definition is None or value.unit != definition.unit or not math.isfinite(value.value):
        return False
    if definition.minimum is not None and value.value < definition.minimum:
        return False
    if definition.maximum is not None and value.value > definition.maximum:
        return False
    if value.name in _INTEGER_METRICS and not float(value.value).is_integer():
        return False
    labels = dict(value.labels)
    if len(labels) != len(value.labels) or set(labels) != set(definition.labels):
        return False
    for key, label in labels.items():
        if key == "core":
            if not label.isascii() or not label.isdecimal() or len(label) > 3 or int(label) > 255:
                return False
        elif key == "mount":
            if label != "/data":
                return False
        elif key == "type":
            if label not in _THERMAL_TYPES:
                return False
        elif not _LABEL.fullmatch(label) or (key == "interface" and len(label) > 32):
            return False
    return True
