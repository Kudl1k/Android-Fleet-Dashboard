"""Vendor GPU telemetry selected by sysfs evidence, never by chipset strings alone.

Each backend owns a detection guard and a parser for ``key=value`` lines emitted by
one bounded script. Adding a platform (Exynos Xclipse, MediaTek APU, NPU/DSP) means
adding a backend with its own script section and parser; unknown hardware yields no
observations instead of fabricated zeros.
"""

from collections.abc import Callable
from dataclasses import dataclass

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_script, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

# Qualcomm Adreno (kgsl) first; Arm Mali (Google Tensor, Exynos, MediaTek) second.
GPU_SCRIPT = """k=/sys/class/kgsl/kgsl-3d0
if [ -d "$k" ]; then
 echo vendor=adreno
 v=; read -r v < "$k/gpu_busy_percentage" && echo "busy_percent=$v"
 v=; read -r v < "$k/gpubusy" && echo "gpubusy=$v"
 v=; read -r v < "$k/devfreq/cur_freq" || read -r v < "$k/gpuclk"; [ -n "$v" ] && echo "cur_hz=$v"
 v=; read -r v < "$k/max_gpuclk" && echo "max_hz=$v"
 exit 0
fi
for m in /sys/devices/platform/*.mali /sys/class/misc/mali0/device; do
 [ -d "$m" ] || continue
 echo vendor=mali
 v=; read -r v < "$m/utilization" && echo "utilization=$v"
 v=; read -r v < "$m/cur_freq" && echo "cur_khz=$v"
 v=; read -r v < "$m/max_freq" && echo "max_khz=$v"
 exit 0
done 2>/dev/null"""


def _number(raw: str | None, *, limit: int = 15) -> float | None:
    text = (raw or "").strip().rstrip("%").strip()
    if not text or len(text) > limit:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


def _hertz(raw: str | None, scale: float) -> float | None:
    value = _number(raw)
    return value * scale if value else None


def parse_adreno(fields: dict[str, str]) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = []
    usage = _number(fields.get("busy_percent"))
    if usage is not None:
        values.append(MetricValue("gpu_usage", usage / 100, "ratio"))
    else:
        # gpubusy reports busy and total time of the last kgsl sampling window.
        window = (fields.get("gpubusy") or "").split()
        busy = _number(window[0]) if len(window) == 2 else None
        total = _number(window[1]) if len(window) == 2 else None
        if busy is not None and total:
            values.append(MetricValue("gpu_usage", busy / total, "ratio"))
    current, maximum = _hertz(fields.get("cur_hz"), 1), _hertz(fields.get("max_hz"), 1)
    if current is not None:
        values.append(MetricValue("gpu_frequency", current, "hertz"))
    if maximum is not None:
        values.append(MetricValue("gpu_max_frequency", maximum, "hertz"))
    return tuple(values)


def parse_mali(fields: dict[str, str]) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = []
    usage = _number(fields.get("utilization"))
    if usage is not None:
        values.append(MetricValue("gpu_usage", usage / 100, "ratio"))
    current, maximum = _hertz(fields.get("cur_khz"), 1000), _hertz(fields.get("max_khz"), 1000)
    if current is not None:
        values.append(MetricValue("gpu_frequency", current, "hertz"))
    if maximum is not None:
        values.append(MetricValue("gpu_max_frequency", maximum, "hertz"))
    return tuple(values)


@dataclass(frozen=True)
class GpuBackend:
    vendor: str
    parse: Callable[[dict[str, str]], tuple[MetricValue, ...]]


BACKENDS = {
    backend.vendor: backend
    for backend in (
        GpuBackend("adreno", parse_adreno),
        GpuBackend("mali", parse_mali),
    )
}


def parse_gpu(output: str) -> tuple[str | None, tuple[MetricValue, ...]]:
    fields: dict[str, str] = {}
    for line in output.splitlines()[:16]:
        key, separator, value = line.partition("=")
        if separator and key.isidentifier() and key not in fields:
            fields[key] = value.strip()[:64]
    backend = BACKENDS.get(fields.get("vendor", ""))
    if backend is None:
        return None, ()
    return backend.vendor, tuple(v for v in backend.parse(fields) if valid_metric(v))


class GpuCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    def supports(self, device: Device) -> bool:
        return can_collect(device)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not self.supports(device):
            return snapshot(device)
        output = await read_script(adb, device, GPU_SCRIPT, self._timeout)
        _, values = parse_gpu(output) if output is not None else (None, ())
        if values:
            device.capabilities.add(DeviceCapability.GPU_METRICS)
        return snapshot(device, values)
