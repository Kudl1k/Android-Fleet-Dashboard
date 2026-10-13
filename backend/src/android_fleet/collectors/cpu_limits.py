"""Per-core frequency ceilings; a policy limit below hardware maximum reveals capping.

Thermal mitigation on Android lowers ``scaling_max_freq`` through cpufreq cooling
devices, but power HALs can also lower it. The exported cap is therefore evidence of
a frequency limit, not proof of thermal throttling on its own; dashboards combine it
with temperatures and the Android thermal status.
"""

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_script, snapshot, validate_timeout
from android_fleet.devices.models import Device
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

CPU_LIMITS_SCRIPT = """for p in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do
 c=${p#/sys/devices/system/cpu/cpu}; c=${c%%/*}
 case "$c" in ''|*[!0-9]*) continue;; esac
 m=; l=
 read -r m < "$p/cpuinfo_max_freq"; read -r l < "$p/scaling_max_freq"
 printf '%s %s %s\\n' "$c" "$m" "$l"
done 2>/dev/null"""


def _khz(raw: str) -> int | None:
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
        return None
    value = int(raw)
    return value if 0 < value <= 100_000_000 else None


def parse_cpu_limits(output: str) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = []
    observed: set[str] = set()
    capped: bool | None = None
    for line in output.splitlines()[:256]:
        fields = line.split()
        if len(fields) != 3 or not fields[0].isascii() or not fields[0].isdecimal():
            continue
        core = str(int(fields[0]))
        if int(core) > 255 or core in observed:
            continue
        maximum, limit = _khz(fields[1]), _khz(fields[2])
        if maximum is None or limit is None:
            continue
        observed.add(core)
        labels = (("core", core),)
        values.append(MetricValue("cpu_max_frequency", maximum * 1000.0, "hertz", labels))
        values.append(MetricValue("cpu_frequency_limit", limit * 1000.0, "hertz", labels))
        capped = bool(capped) or limit < maximum
    if capped is not None:
        values.append(MetricValue("cpu_frequency_capped", float(capped), "boolean"))
    return tuple(value for value in values if valid_metric(value))


class CpuLimitsCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_script(adb, device, CPU_LIMITS_SCRIPT, self._timeout)
        return snapshot(device, parse_cpu_limits(output) if output is not None else ())
