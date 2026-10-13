"""Live Android HAL temperatures; thresholds, cooling and BCL units are excluded."""

import re

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import (
    can_collect,
    read_script,
    read_shell,
    snapshot,
    validate_timeout,
)
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

THERMAL_SCRIPT = """n=0
for p in /sys/class/thermal/thermal_zone[0-9]*; do
 [ "$n" -lt 32 ] || break
 n=$((n+1))
 t=$(cat "$p/type" 2>/dev/null) || continue
 v=$(cat "$p/temp" 2>/dev/null) || continue
 printf '%s|%s|%s\\n' "${p##*/}" "$t" "$v"
done"""
_TYPES = {
    -1: "unknown",
    0: "cpu",
    1: "gpu",
    2: "battery",
    3: "skin",
    4: "usb",
    5: "power_amplifier",
    9: "npu",
}


def _sensor(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", name.strip())[:64]


def parse_thermal(output: str) -> tuple[MetricValue, ...]:
    values: dict[tuple[str, str], MetricValue] = {}
    status: MetricValue | None = None
    live = False
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("Thermal Status:"):
            try:
                candidate = MetricValue("thermal_status", float(text.partition(":")[2]), "level")
            except ValueError:
                continue
            if valid_metric(candidate) and candidate.value.is_integer():
                status = candidate
        if text == "Current temperatures from HAL:":
            live = True
            continue
        if text.endswith(":") and not text.startswith("Temperature{"):
            live = False
        if not live:
            continue
        match = re.search(r"\bTemperature\{([^}]+)\}", text)
        if not match:
            continue
        fields = dict(re.findall(r"(mValue|mType|mName|mStatus)=([^,}]+)", match[1]))
        try:
            type_number = int(fields.get("mType", "invalid"))
            temperature = float(fields.get("mValue", "invalid"))
        except ValueError:
            continue
        if type_number not in _TYPES:
            continue
        sensor = _sensor(fields.get("mName", ""))
        kind = _TYPES[type_number]
        value = MetricValue(
            "thermal_temperature", temperature, "celsius", (("sensor", sensor), ("type", kind))
        )
        key = (sensor, kind)
        if valid_metric(value) and (key in values or len(values) < 32):
            values[key] = value
    result = tuple(values.values())
    return result + ((status,) if status is not None else ())


def parse_thermal_sysfs(output: str) -> tuple[MetricValue, ...]:
    values: dict[tuple[str, str], MetricValue] = {}
    for line in output.splitlines()[:32]:
        fields = line.split("|")
        if len(fields) != 3 or re.fullmatch(r"thermal_zone[0-9]+", fields[0]) is None:
            continue
        zone, raw_type, raw_temperature = fields
        raw_type = raw_type.strip().lower()
        # Battery Current Limiter zones can report volts, amperes or percentages.
        if "bcl" in raw_type:
            continue
        kind = next(
            (kind for kind in ("cpu", "gpu", "battery", "skin", "usb", "npu") if kind in raw_type),
            "unknown",
        )
        sensor = _sensor(zone + ":" + raw_type)
        try:
            temperature = float(raw_temperature) / 1000
        except ValueError:
            continue
        value = MetricValue(
            "thermal_temperature", temperature, "celsius", (("sensor", sensor), ("type", kind))
        )
        if valid_metric(value):
            values[(sensor, kind)] = value
    return tuple(values.values())


class ThermalCollector:
    def __init__(self, *, timeout: float = 5.0, sysfs_fallback: bool = True) -> None:
        self._timeout = validate_timeout(timeout)
        self._sysfs_fallback = sysfs_fallback

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("dumpsys", "thermalservice"), self._timeout)
        values = parse_thermal(output) if output is not None else ()
        if self._sysfs_fallback and not any(v.name == "thermal_temperature" for v in values):
            # Thermal zones are frequently root-only; read_script elevates where available.
            output = await read_script(adb, device, THERMAL_SCRIPT, self._timeout)
            if output is not None:
                values += parse_thermal_sysfs(output)
        if values:
            device.capabilities.add(DeviceCapability.THERMAL_BASIC)
        return snapshot(device, values)
