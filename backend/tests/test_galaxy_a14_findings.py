"""Regressions found while testing a non-rooted Samsung Galaxy A14 (Android 14)."""

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.collectors.battery import parse_battery_capacity
from android_fleet.collectors.storage import StorageCollector, parse_diskstats
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.metrics.catalog import valid_metric

DISKSTATS = """Latency: 3ms [512B Data Write]
Recent Disk Write Speed (kB/s) = 51234
Data-Free: 30212456K / 52428800K total = 57% free
Cache-Free: 30212456K / 52428800K total = 57% free
System-Free: 0K / 4194304K total = 0% free
"""


def test_diskstats_reports_data_partition_without_root() -> None:
    values = {value.name: value.value for value in parse_diskstats(DISKSTATS)}
    assert values == {
        "storage_total": 52428800 * 1024,
        "storage_used": (52428800 - 30212456) * 1024,
        "storage_free": 30212456 * 1024,
    }
    assert all(valid_metric(value) for value in parse_diskstats(DISKSTATS))
    assert parse_diskstats("Data-Free: 10K / 5K total") == ()
    assert parse_diskstats("permission denied") == ()


async def test_storage_falls_back_to_diskstats_when_df_is_denied() -> None:
    class Adb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
        ) -> CommandResult:
            if argv == ("df", "-k", "/data"):
                return CommandResult(stdout="df: /data: Permission denied", exit_code=1)
            if argv == ("dumpsys", "diskstats"):
                return CommandResult(stdout=DISKSTATS)
            return CommandResult(exit_code=1)

    device = Device(
        "phone", "serial", "Phone", DeviceState.ONLINE, capabilities={DeviceCapability.ADB_SHELL}
    )
    values = (await StorageCollector().collect(device, Adb())).values
    assert {value.name for value in values} == {"storage_total", "storage_used", "storage_free"}
    assert DeviceCapability.STORAGE_METRICS in device.capabilities


def test_contradictory_design_capacity_is_withheld() -> None:
    names = {
        value.name: value.value
        for value in parse_battery_capacity(
            "charge_full=2946000\ncharge_full_design=294600\ncycle_count=364"
        )
    }
    assert names == {"battery_charge_full": 2.946, "battery_cycle_count": 364}
    consistent = {
        value.name
        for value in parse_battery_capacity("charge_full=2900000\ncharge_full_design=3000000")
    }
    assert consistent == {"battery_charge_full", "battery_charge_full_design"}
