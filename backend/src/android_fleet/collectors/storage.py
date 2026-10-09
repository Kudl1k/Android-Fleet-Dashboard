"""Bounded /data storage observations from portable df -k output."""

import re

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def parse_storage(output: str) -> tuple[MetricValue, ...]:
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        mount = fields[-1]
        # Android may resolve /data to a bind-mounted per-user data directory.
        # Keep the dimension tied to the queried logical capacity, not that path.
        if (
            len(mount) > 256
            or re.fullmatch(r"/data(?:/[A-Za-z0-9_.:-]{1,64}){0,8}", mount) is None
            or any(part in {".", ".."} for part in mount.split("/"))
        ):
            continue
        try:
            total, used, free = (int(value) for value in fields[-5:-2])
        except ValueError:
            continue
        if (
            not 0 < total <= (2**63 - 1) // 1024
            or not 0 <= used <= total
            or not 0 <= free <= total
            or used + free > total
        ):
            continue
        return tuple(
            MetricValue(f"storage_{name}", float(value * 1024), "bytes", (("mount", "/data"),))
            for name, value in (("total", total), ("used", used), ("free", free))
        )
    return ()


class StorageCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("df", "-k", "/data"), self._timeout)
        values = parse_storage(output) if output is not None else ()
        if values:
            device.capabilities.add(DeviceCapability.STORAGE_METRICS)
        return snapshot(device, values)
