"""/proc/meminfo KiB observations, preserving independent partial fields."""

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def parse_memory(output: str) -> tuple[MetricValue, ...]:
    parsed: dict[str, int] = {}
    for line in output.splitlines():
        key, _, raw = line.partition(":")
        if key not in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            continue
        parts = raw.split()
        if len(parts) != 2 or parts[1] != "kB":
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        if 0 <= value <= (2**63 - 1) // 1024:
            parsed[key] = value * 1024
    total, available = parsed.get("MemTotal"), parsed.get("MemAvailable")
    if total is not None and available is not None and available > total:
        available = None
    values: list[MetricValue] = []
    if total is not None:
        values.append(MetricValue("memory_total", float(total), "bytes"))
    if available is not None:
        values.append(MetricValue("memory_available", float(available), "bytes"))
    if total is not None and available is not None:
        values.append(MetricValue("memory_used", float(total - available), "bytes"))
    swap_total, swap_free = parsed.get("SwapTotal"), parsed.get("SwapFree")
    if swap_total is not None and swap_free is not None and swap_free <= swap_total:
        values.append(MetricValue("swap_used", float(swap_total - swap_free), "bytes"))
    return tuple(values)


class MemoryCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if (
            device.state != DeviceState.ONLINE
            or DeviceCapability.MEMORY_METRICS not in device.capabilities
        ):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("cat", "/proc/meminfo"), self._timeout)
        return snapshot(device, parse_memory(output) if output is not None else ())
