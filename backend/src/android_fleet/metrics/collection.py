"""Bounded collection independent of HTTP, persistence and connectivity scheduling."""

import asyncio
from datetime import UTC, datetime

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.base import Collector
from android_fleet.collectors.battery import BatteryCollector
from android_fleet.collectors.cpu import CpuCollector
from android_fleet.collectors.cpu_limits import CpuLimitsCollector
from android_fleet.collectors.gpu import GpuCollector
from android_fleet.collectors.memory import MemoryCollector
from android_fleet.collectors.network import NetworkCollector
from android_fleet.collectors.npu import NpuCollector
from android_fleet.collectors.processes import ProcessCollector
from android_fleet.collectors.storage import StorageCollector
from android_fleet.collectors.thermal import ThermalCollector
from android_fleet.collectors.uptime import UptimeCollector
from android_fleet.collectors.zram import ZramCollector
from android_fleet.devices.models import Device
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue


class MetricPipeline:
    def __init__(self, *, command_timeout: float = 5, cycle_timeout: float = 20) -> None:
        self.command_timeout = command_timeout
        self.cycle_timeout = cycle_timeout
        self._collectors: dict[str, tuple[Collector, ...]] = {}

    def reset(self, device_id: str) -> None:
        # Dropping the bundle also discards CPU delta baselines across reconnects.
        self._collectors.pop(device_id, None)

    def _bundle(self, device_id: str) -> tuple[Collector, ...]:
        if device_id not in self._collectors:
            self._collectors[device_id] = (
                BatteryCollector(timeout=self.command_timeout),
                CpuCollector(timeout=self.command_timeout),
                MemoryCollector(timeout=self.command_timeout),
                StorageCollector(timeout=self.command_timeout),
                NetworkCollector(timeout=self.command_timeout),
                UptimeCollector(timeout=self.command_timeout),
                ThermalCollector(timeout=self.command_timeout),
                CpuLimitsCollector(timeout=self.command_timeout),
                ZramCollector(timeout=self.command_timeout),
                GpuCollector(timeout=self.command_timeout),
                NpuCollector(timeout=self.command_timeout),
                ProcessCollector(timeout=self.command_timeout),
            )
        return self._collectors[device_id]

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        values: dict[tuple[str, tuple[tuple[str, str], ...]], MetricValue] = {}
        try:
            async with asyncio.timeout(self.cycle_timeout):
                for collector in self._bundle(device.id):
                    try:
                        snapshot = await collector.collect(device, adb)
                    except (OSError, RuntimeError, TimeoutError, ValueError):
                        continue
                    for value in snapshot.values:
                        if valid_metric(value):
                            normalized = MetricValue(
                                value.name, value.value, value.unit, tuple(sorted(value.labels))
                            )
                            values[(value.name, normalized.labels)] = normalized
        except TimeoutError:
            # Preserve successful collectors even if a later source exhausts the budget.
            pass
        return MetricSnapshot(device.id, datetime.now(UTC), tuple(values.values()))
