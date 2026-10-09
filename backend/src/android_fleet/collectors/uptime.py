"""Device boot uptime, distinct from management-host observation time."""

import math

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def parse_uptime(output: str) -> tuple[MetricValue, ...]:
    fields = output.split()
    if len(fields) != 2:
        return ()
    try:
        value = MetricValue("uptime", float(fields[0]), "seconds")
        idle = float(fields[1])
    except ValueError:
        return ()
    return (value,) if valid_metric(value) and math.isfinite(idle) and idle >= 0 else ()


class UptimeCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("cat", "/proc/uptime"), self._timeout)
        values = parse_uptime(output) if output is not None else ()
        if values:
            device.capabilities.add(DeviceCapability.UPTIME_METRICS)
        return snapshot(device, values)
