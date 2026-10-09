from datetime import UTC, datetime
from pathlib import Path

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.collectors.battery import BatteryCollector, parse_battery
from android_fleet.collectors.memory import MemoryCollector, parse_memory
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.metrics.exporter import render_metrics
from android_fleet.metrics.models import MetricSnapshot, MetricValue

FIXTURES = Path(__file__).parent / "fixtures"


def test_fixture_parsers() -> None:
    assert parse_battery((FIXTURES / "battery.txt").read_text()) == (
        MetricValue("battery_level", 0.75, "ratio"),
        MetricValue("battery_temperature", 28.5, "celsius"),
        MetricValue("battery_voltage", 4.1, "volts"),
        MetricValue("battery_status", 2, "level"),
        MetricValue("battery_charging", 1, "boolean"),
        MetricValue("battery_health", 2, "level"),
    )
    assert {v.name: v.value for v in parse_memory((FIXTURES / "meminfo.txt").read_text())} == {
        "memory_total": 8192000000.0,
        "memory_available": 3072000000.0,
        "memory_used": 5120000000.0,
        "swap_used": 102400000.0,
    }
    assert parse_battery((FIXTURES / "malformed_battery.txt").read_text()) == ()
    assert parse_memory((FIXTURES / "malformed_meminfo.txt").read_text()) == ()


@pytest.mark.parametrize(
    "output",
    [
        "",
        "level: ???",
        "level: nan\nscale: 100",
        "level: 2\nscale: 0",
        "level: 101\nscale: 100",
        "level: -1\nscale: 100",
    ],
)
def test_invalid_battery_is_omitted(output: str) -> None:
    assert parse_battery(output) == ()


@pytest.mark.parametrize(
    "output",
    ["", "MemTotal: ??? kB", "MemAvailable: -1 kB", "MemTotal: 2 MB", "MemTotal: 1e309 kB"],
)
def test_invalid_memory_is_omitted(output: str) -> None:
    assert parse_memory(output) == ()


def test_memory_preserves_partial_observations() -> None:
    assert parse_memory("MemTotal: 100 kB\nMemAvailable: 101 kB") == (
        MetricValue("memory_total", 102400, "bytes"),
    )
    assert parse_memory("MemAvailable: 0 kB") == (MetricValue("memory_available", 0, "bytes"),)


@pytest.mark.parametrize(
    "serial", ["pixel-rooted", "pixel-stock", "pixel-malformed", "pixel-offline"]
)
async def test_collectors_use_fake_devices(serial: str) -> None:
    adb = FakeAdbClient()
    device = Device(
        serial,
        serial,
        serial,
        adb.devices[serial],
        capabilities={DeviceCapability.BATTERY_METRICS, DeviceCapability.MEMORY_METRICS},
    )
    battery = await BatteryCollector().collect(device, adb)
    memory = await MemoryCollector().collect(device, adb)
    assert bool(battery.values) == (serial in {"pixel-rooted", "pixel-stock"})
    assert bool(memory.values) == (serial in {"pixel-rooted", "pixel-stock"})
    if serial == "pixel-offline":
        assert not adb.calls


async def test_missing_capabilities_do_not_execute_commands() -> None:
    adb = FakeAdbClient()
    device = Device("d", "pixel-stock", "d", DeviceState.ONLINE)
    assert not (await BatteryCollector().collect(device, adb)).values
    assert not (await MemoryCollector().collect(device, adb)).values
    assert not adb.calls


class FailedAdb(FakeAdbClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        raise self.error


@pytest.mark.parametrize("error", [TimeoutError(), OSError(), RuntimeError()])
async def test_collector_failure_does_not_abort_polling(error: Exception) -> None:
    device = Device(
        "d",
        "d",
        "d",
        DeviceState.ONLINE,
        capabilities={DeviceCapability.BATTERY_METRICS, DeviceCapability.MEMORY_METRICS},
    )
    assert not (await BatteryCollector().collect(device, FailedAdb(error))).values
    assert not (await MemoryCollector().collect(device, FailedAdb(error))).values


def test_exporter_omits_unknown_root_and_stale_offline_metrics() -> None:
    online = Device("online", "online", "online", DeviceState.ONLINE)
    offline = Device("offline", "offline", "offline", DeviceState.OFFLINE)
    snapshot = MetricSnapshot(
        "offline", datetime.now(UTC), (MetricValue("battery_level", 0.2, "ratio"),)
    )
    output = render_metrics([online, offline], {"offline": snapshot}).decode()
    assert 'android_device_up{device_id="online"} 1.0' in output
    assert 'android_device_up{device_id="offline"} 0.0' in output
    assert "android_device_rooted{device_id=" not in output
    assert "android_battery_level_ratio{device_id=" not in output


def test_exporter_maps_normalized_values_and_filters_invalid_metrics() -> None:
    device = Device("d", "d", "d", DeviceState.ONLINE, root_available=False)
    snapshot = MetricSnapshot(
        "d",
        datetime.now(UTC),
        (
            MetricValue("battery_level", 0.75, "ratio"),
            MetricValue("memory_total", float("nan"), "bytes"),
            MetricValue("memory_available", 10, "wrong"),
            MetricValue("untrusted_dynamic_name", 1, "bytes"),
        ),
    )
    output = render_metrics([device], {"d": snapshot}).decode()
    assert 'android_battery_level_ratio{device_id="d"} 0.75' in output
    assert 'android_device_rooted{device_id="d"} 0.0' in output
    assert "android_memory_total_bytes{device_id=" not in output
    assert "android_memory_available_bytes{device_id=" not in output
    assert "untrusted_dynamic_name" not in output
