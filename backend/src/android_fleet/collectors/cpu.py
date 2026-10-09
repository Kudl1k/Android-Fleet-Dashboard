"""CPU usage is a counter delta, never a fabricated first-poll percentage."""

import re

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

FREQUENCY_SCRIPT = """n=0
for p in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
 c=${p#/sys/devices/system/cpu/cpu}; c=${c%%/*}
 case "$c" in ''|*[!0-9]*) continue;; esac
 [ "$c" -le 255 ] || continue
 v=$(cat "$p" 2>/dev/null) || continue
 printf '%s %s\\n' "$c" "$v"
 n=$((n+1)); [ "$n" -lt 256 ] || break
done"""


def parse_cpu_stat(output: str) -> dict[str, tuple[int, ...]]:
    samples: dict[str, tuple[int, ...]] = {}
    for line in output.splitlines():
        fields = line.split()
        if not fields or re.fullmatch(r"cpu(?:[0-9]{1,3})?", fields[0]) is None:
            continue
        core = fields[0][3:]
        if core and int(core) > 255:
            continue
        if len(fields) < 5 or any(
            not v.isascii() or not v.isdecimal() or len(v) > 19 for v in fields[1:]
        ):
            continue
        counters = tuple(int(value) for value in fields[1:9])
        if any(value > 2**63 - 1 for value in counters):
            continue
        # user/nice already include guest/guest_nice; do not count columns 9/10 twice.
        samples[fields[0]] = counters + (0,) * (8 - len(counters))
    return samples


def cpu_delta(
    previous: dict[str, tuple[int, ...]], current: dict[str, tuple[int, ...]]
) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = []
    for key, counters in current.items():
        old = previous.get(key)
        if old is None or any(new < before for new, before in zip(counters, old, strict=True)):
            continue
        delta = tuple(new - before for new, before in zip(counters, old, strict=True))
        total = sum(delta)
        if total == 0:
            continue
        usage = (total - delta[3] - delta[4]) / total
        values.append(
            MetricValue("cpu_usage", usage, "ratio")
            if key == "cpu"
            else MetricValue("cpu_core_usage", usage, "ratio", (("core", str(int(key[3:]))),))
        )
    return tuple(values)


def parse_cpuinfo(output: str) -> tuple[MetricValue, ...]:
    for line in output.splitlines():
        match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)%\s+TOTAL(?:\s|:|$)", line)
        if match:
            value = MetricValue("cpu_usage", float(match[1]) / 100, "ratio")
            return (value,) if valid_metric(value) else ()
    return ()


def parse_frequencies(output: str) -> tuple[MetricValue, ...]:
    values: dict[str, MetricValue] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 2 or any(
            not v.isascii() or not v.isdecimal() or len(v) > 10 for v in fields
        ):
            continue
        core, frequency = int(fields[0]), int(fields[1])
        if core > 255 or frequency <= 0 or frequency > 100_000_000:
            continue
        value = MetricValue(
            "cpu_frequency", float(frequency * 1000), "hertz", (("core", str(core)),)
        )
        values[str(core)] = value
    return tuple(values.values())


class CpuCollector:
    def __init__(self, *, timeout: float = 5.0, collect_frequency: bool = True) -> None:
        self._timeout = validate_timeout(timeout)
        self._collect_frequency = collect_frequency
        self._previous: dict[str, dict[str, tuple[int, ...]]] = {}

    def reset(self, device_id: str) -> None:
        self._previous.pop(device_id, None)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            self.reset(device.id)
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("cat", "/proc/stat"), self._timeout)
        counters = parse_cpu_stat(output) if output is not None else {}
        values: tuple[MetricValue, ...] = ()
        if "cpu" in counters:
            values = cpu_delta(self._previous.get(device.id, {}), counters)
            self._previous[device.id] = counters
            device.capabilities.add(DeviceCapability.CPU_METRICS)
        else:
            self.reset(device.id)
            fallback = await read_shell(adb, device.serial, ("dumpsys", "cpuinfo"), self._timeout)
            values = parse_cpuinfo(fallback) if fallback is not None else ()
        if self._collect_frequency:
            frequency = await read_shell(
                adb, device.serial, ("sh", "-c", FREQUENCY_SCRIPT), self._timeout
            )
            if frequency is not None:
                values += parse_frequencies(frequency)
        if values:
            device.capabilities.add(DeviceCapability.CPU_METRICS)
        return snapshot(device, values)
