"""Read-only NPU devfreq backend; frequency is not treated as utilization.

Only devfreq devices explicitly named NPU are eligible. Other accelerators need
an explicit backend with documented units; unknown busy counters are not guessed.
"""

import re

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_script, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

NPU_SCRIPT = """n=0
for p in /sys/class/devfreq/*; do
 [ -d "$p" ] || continue
 name=${p##*/}
 case "$name" in *npu*|*NPU*) ;; *) continue;; esac
 [ "$n" -lt 8 ] || break
 n=$((n+1))
 v=$(cat "$p/cur_freq" 2>/dev/null) || continue
 printf '%s|%s\\n' "$name" "$v"
done"""


def parse_npu(output: str) -> tuple[MetricValue, ...]:
    values: dict[str, MetricValue] = {}
    for line in output.splitlines()[:8]:
        name, separator, raw = line.partition("|")
        if not separator or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name):
            continue
        if "npu" not in name.lower() or not re.fullmatch(r"[0-9]{1,12}", raw):
            continue
        frequency = int(raw)
        if not 0 < frequency <= 100_000_000_000:
            continue
        value = MetricValue("npu_frequency", float(frequency), "hertz", (("accelerator", name),))
        if valid_metric(value):
            values[name] = value
    return tuple(values.values())


class NpuCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    def supports(self, device: Device) -> bool:
        return can_collect(device)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not self.supports(device):
            return snapshot(device)
        output = await read_script(adb, device, NPU_SCRIPT, self._timeout)
        values = parse_npu(output) if output is not None else ()
        if values:
            device.capabilities.add(DeviceCapability.NPU_METRICS)
        return snapshot(device, values)
