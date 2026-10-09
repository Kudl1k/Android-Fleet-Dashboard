"""Collector interfaces independent of API and monitoring transports."""

from typing import Protocol

from android_fleet.adb.base import AdbClient
from android_fleet.devices.models import Device
from android_fleet.metrics.models import MetricSnapshot


class Collector(Protocol):
    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot: ...


class HardwareCollector(Collector, Protocol):
    """Vendor plugins must explicitly match discovered hardware and capabilities."""

    def supports(self, device: Device) -> bool: ...
