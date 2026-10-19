from collections.abc import Callable
from pathlib import Path

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.collectors.base import Collector
from android_fleet.collectors.battery import BatteryCollector, parse_battery, parse_battery_current
from android_fleet.collectors.cpu import (
    FREQUENCY_SCRIPT,
    CpuCollector,
    cpu_delta,
    parse_cpu_stat,
    parse_cpuinfo,
    parse_frequencies,
)
from android_fleet.collectors.memory import MemoryCollector, parse_memory
from android_fleet.collectors.network import NetworkCollector, parse_ip_link, parse_network
from android_fleet.collectors.storage import StorageCollector, parse_storage
from android_fleet.collectors.thermal import (
    THERMAL_SCRIPT,
    ThermalCollector,
    parse_thermal,
    parse_thermal_sysfs,
)
from android_fleet.collectors.uptime import UptimeCollector, parse_uptime
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricValue

FIXTURES = Path(__file__).parent / "fixtures" / "m2"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def device(serial: str = "pixel-stock") -> Device:
    return Device(
        serial,
        serial,
        serial,
        DeviceState.ONLINE,
        capabilities={
            DeviceCapability.ADB_SHELL,
            DeviceCapability.BATTERY_METRICS,
            DeviceCapability.MEMORY_METRICS,
        },
    )


class FixtureAdb(FakeAdbClient):
    def __init__(self, outputs: dict[tuple[str, ...], CommandResult]) -> None:
        super().__init__()
        self.outputs = outputs
        self.timeouts: list[float] = []

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        self.calls.append((serial, argv))
        self.timeouts.append(timeout)
        return self.outputs.get(
            argv, CommandResult(stderr=fixture("permission_denied.txt"), exit_code=1)
        )


def ok(output: str) -> CommandResult:
    return CommandResult(stdout=output)


def test_richer_battery_and_memory_units_without_fabricated_values() -> None:
    assert {v.name: v.value for v in parse_battery(fixture("battery.txt"))} == {
        "battery_level": 0.75,
        "battery_temperature": 28.5,
        "battery_voltage": 4.1,
    }
    assert parse_battery_current("-500000\n") == (MetricValue("battery_current", -0.5, "amperes"),)
    assert parse_battery_current("0") == (MetricValue("battery_current", 0, "amperes"),)
    assert parse_battery_current("permission denied") == ()
    assert parse_battery_current("NaN") == ()
    assert parse_battery("level: invalid\nscale: 100\ntemperature: 300") == (
        MetricValue("battery_temperature", 30, "celsius"),
    )
    assert {v.name: v.value for v in parse_memory(fixture("memory.txt"))} == {
        "memory_total": 8192000000,
        "memory_available": 3072000000,
        "memory_used": 5120000000,
        "swap_used": 1024000000,
    }
    assert parse_memory("SwapTotal: 2 kB\nSwapFree: 3 kB") == ()
    assert parse_memory("SwapTotal: 2 kB") == ()


def test_cpu_delta_excludes_guest_and_requires_two_samples() -> None:
    first, second = (
        parse_cpu_stat(fixture("stat_first.txt")),
        parse_cpu_stat(fixture("stat_second.txt")),
    )
    assert cpu_delta({}, first) == ()
    values = cpu_delta(first, second)
    assert values[0] == MetricValue("cpu_usage", 0.5, "ratio")
    assert values[1:] == (
        MetricValue("cpu_core_usage", 0.5, "ratio", (("core", "0"),)),
        MetricValue("cpu_core_usage", 0.5, "ratio", (("core", "1"),)),
    )
    assert cpu_delta(second, first) == ()  # counter reset/wrap
    assert cpu_delta(second, second) == ()
    assert parse_cpuinfo(fixture("cpuinfo.txt")) == (MetricValue("cpu_usage", 0.125, "ratio"),)
    assert parse_frequencies("0 1800000\n255 2000000\n256 3000000\n1 -1") == (
        MetricValue("cpu_frequency", 1800000000, "hertz", (("core", "0"),)),
        MetricValue("cpu_frequency", 2000000000, "hertz", (("core", "255"),)),
    )


def test_storage_network_uptime_fixtures() -> None:
    assert {v.name: v.value for v in parse_storage(fixture("storage.txt"))} == {
        "storage_total": 10240000000,
        "storage_used": 7168000000,
        "storage_free": 3072000000,
    }
    network = parse_network(fixture("network.txt"))
    assert network == parse_ip_link(fixture("ip_link.txt"))
    assert len(network) == 4
    assert all(dict(v.labels)["interface"] != "lo" for v in network)
    assert network[0].value == 123456
    assert parse_uptime(fixture("uptime.txt")) == (MetricValue("uptime", 12345.67, "seconds"),)


def test_thermal_live_readings_exclude_stale_thresholds_cooling_and_bcl() -> None:
    values = parse_thermal(fixture("thermal.txt"))
    assert values == (
        MetricValue("thermal_temperature", 45, "celsius", (("sensor", "CPU"), ("type", "cpu"))),
        MetricValue(
            "thermal_temperature", 35, "celsius", (("sensor", "battery"), ("type", "battery"))
        ),
        MetricValue("thermal_status", 2, "level"),
    )
    sysfs = parse_thermal_sysfs(fixture("thermal_sysfs.txt"))
    assert len(sysfs) == 3
    assert {v.value for v in sysfs} == {44, 42, 35}
    assert all(valid_metric(value) for value in sysfs)
    assert parse_thermal("Cached temperatures:\n Temperature{mValue=99, mType=0, mName=CPU}") == ()


@pytest.mark.parametrize(
    ("parser", "output"),
    [
        (parse_cpuinfo, "101% TOTAL: invalid"),
        (parse_cpuinfo, "NaN% TOTAL: invalid"),
        (parse_cpuinfo, "12% system_server: 12% user"),
        (parse_storage, "/dev/dm 100 90 50 1% /data"),
        (parse_storage, "/dev/dm 100 -10 110 1% /data"),
        (parse_storage, "/dev/dm 100 50 50 50% /system"),
        (parse_network, "wlan0: nan 0 0 0 0 0 0 0 100 0 0 0 0 0 0 0"),
        (parse_uptime, "NaN 123"),
        (parse_uptime, "123 nan"),
        (parse_uptime, "123 denied"),
        (parse_uptime, "-1 123"),
        (parse_uptime, "permission denied"),
        (
            parse_thermal,
            "Current temperatures from HAL:\n Temperature{mValue=500, mType=0, mName=cpu}",
        ),
        (parse_thermal_sysfs, "thermal_zone0|cpu|NaN"),
    ],
)
def test_malformed_and_unsupported_output_omitted(
    parser: Callable[[str], tuple[MetricValue, ...]], output: str
) -> None:
    assert parser(output) == ()


async def test_cpu_first_sample_reset_reconnect_and_failure_rebaseline() -> None:
    adb = FakeAdbClient()
    target = device()
    collector = CpuCollector(collect_frequency=False)
    assert not (await collector.collect(target, adb)).values
    assert DeviceCapability.CPU_METRICS in target.capabilities
    assert (await collector.collect(target, adb)).values[0].value == 0.5
    collector.reset(target.id)
    assert not (await collector.collect(target, adb)).values
    target.state = DeviceState.OFFLINE
    before = len(adb.calls)
    assert not (await collector.collect(target, adb)).values
    assert len(adb.calls) == before
    target.state = DeviceState.ONLINE
    assert not (await collector.collect(target, adb)).values
    assert (await collector.collect(target, adb)).values[0].value == 0.5


async def test_cpu_permission_fallback_and_optional_frequency_use_no_root() -> None:
    adb = FixtureAdb(
        {
            ("dumpsys", "cpuinfo"): ok(fixture("cpuinfo.txt")),
            ("sh", "-c", FREQUENCY_SCRIPT): ok("0 1800000"),
        }
    )
    values = (await CpuCollector(timeout=0.5).collect(device(), adb)).values
    assert values[0] == MetricValue("cpu_usage", 0.125, "ratio")
    assert values[1].name == "cpu_frequency"
    assert all(argv[0] != "su" for _, argv in adb.calls)
    assert set(adb.timeouts) == {0.5}


async def test_network_and_thermal_permission_fallbacks() -> None:
    adb = FixtureAdb(
        {
            ("ip", "-s", "link"): ok(fixture("ip_link.txt")),
            ("sh", "-c", THERMAL_SCRIPT): ok(fixture("thermal_sysfs.txt")),
        }
    )
    target = device()
    assert len((await NetworkCollector().collect(target, adb)).values) == 4
    assert len((await ThermalCollector().collect(target, adb)).values) == 3
    assert DeviceCapability.NETWORK_METRICS in target.capabilities
    assert DeviceCapability.THERMAL_BASIC in target.capabilities


@pytest.mark.parametrize(
    "serial", ["pixel-rooted", "pixel-stock", "pixel-offline", "pixel-malformed"]
)
async def test_demo_collectors_rooted_nonrooted_offline_malformed(serial: str) -> None:
    adb = FakeAdbClient()
    target = device(serial)
    target.state = adb.devices[serial]
    collectors: list[Collector] = [
        BatteryCollector(),
        MemoryCollector(),
        CpuCollector(),
        StorageCollector(),
        NetworkCollector(),
        UptimeCollector(),
        ThermalCollector(),
    ]
    snapshots = [await collector.collect(target, adb) for collector in collectors]
    supported = serial in {"pixel-rooted", "pixel-stock"}
    assert all(bool(s.values) == supported for s in snapshots)
    assert all(valid_metric(v) for s in snapshots for v in s.values)
    assert all(argv[0] != "su" for _, argv in adb.calls)
    if serial == "pixel-offline":
        assert not adb.calls


@pytest.mark.parametrize(
    "collector_type",
    [CpuCollector, StorageCollector, NetworkCollector, UptimeCollector, ThermalCollector],
)
async def test_new_collectors_detect_capabilities_only_after_valid_results(
    collector_type: Callable[[], Collector],
) -> None:
    target = device()
    target.capabilities = {DeviceCapability.ADB_SHELL}
    adb = FixtureAdb({})
    assert not (await collector_type().collect(target, adb)).values
    assert target.capabilities == {DeviceCapability.ADB_SHELL}
    target.capabilities.clear()
    adb.calls.clear()
    assert not (await collector_type().collect(target, adb)).values
    assert not adb.calls


async def test_battery_partial_failure_preserves_observed_fields() -> None:
    adb = FixtureAdb({("dumpsys", "battery"): ok(fixture("battery.txt"))})
    snapshot = await BatteryCollector().collect(device(), adb)
    assert {v.name for v in snapshot.values} == {
        "battery_level",
        "battery_temperature",
        "battery_voltage",
    }
    adb.outputs[("dumpsys", "battery")] = CommandResult(stdout=fixture("battery.txt"), timeout=True)
    assert not (await BatteryCollector().collect(device(), adb)).values


def test_dimension_bounds_cpu_network_thermal() -> None:
    assert len(parse_cpu_stat("cpu256 1 1 1 1\ncpu255 1 1 1 1")) == 1
    output = "\n".join(f"wlan{i}: 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0" for i in range(40))
    assert len(parse_network(output)) == 64
    output = "Current temperatures from HAL:\n" + "\n".join(
        f" Temperature{{mValue=40, mType=0, mName=cpu{i}}}" for i in range(40)
    )
    assert len(parse_thermal(output)) == 32
    assert parse_cpu_stat("cpu " + "9" * 5000 + " 1 1 1") == {}
    assert parse_network("wlan0: " + "9" * 5000 + " 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0") == ()


class RaisingAdb(FakeAdbClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
    ) -> CommandResult:
        raise self.error


@pytest.mark.parametrize("error", [OSError("denied"), RuntimeError("adb failed"), TimeoutError()])
async def test_expected_transport_errors_do_not_abort_any_collector(error: Exception) -> None:
    collectors: list[Collector] = [
        BatteryCollector(),
        MemoryCollector(),
        CpuCollector(),
        StorageCollector(),
        NetworkCollector(),
        UptimeCollector(),
        ThermalCollector(),
    ]
    for collector in collectors:
        assert not (await collector.collect(device(), RaisingAdb(error))).values


async def test_cpu_counter_reset_rebaselines_instead_of_emitting_spike() -> None:
    adb = FixtureAdb({("cat", "/proc/stat"): ok(fixture("stat_second.txt"))})
    collector = CpuCollector(collect_frequency=False)
    target = device()
    assert not (await collector.collect(target, adb)).values
    adb.outputs[("cat", "/proc/stat")] = ok(fixture("stat_first.txt"))
    assert not (await collector.collect(target, adb)).values
    adb.outputs[("cat", "/proc/stat")] = ok(fixture("stat_second.txt"))
    assert (await collector.collect(target, adb)).values[0].value == 0.5
    adb.outputs.clear()  # denied sample clears the old baseline
    assert not (await collector.collect(target, adb)).values
    adb.outputs[("cat", "/proc/stat")] = ok(fixture("stat_first.txt"))
    assert not (await collector.collect(target, adb)).values


async def test_storage_accepts_android_data_bind_mount_and_keeps_logical_label() -> None:
    output = fixture("storage_bind_mount.txt")
    values = parse_storage(output)
    assert {v.name: v.value for v in values} == {
        "storage_total": 110454764 * 1024,
        "storage_used": 18672432 * 1024,
        "storage_free": 91651260 * 1024,
    }
    assert all(value.labels == (("mount", "/data"),) for value in values)
    adb = FixtureAdb({("df", "-k", "/data"): ok(output)})
    target = device()
    assert (await StorageCollector().collect(target, adb)).values == values
    assert DeviceCapability.STORAGE_METRICS in target.capabilities


def test_storage_accepts_data_mirror_reported_by_pixel_3a_android_12() -> None:
    output = (
        "Filesystem       1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/dm-34  52389356 16716348  35673008  32% /data_mirror/ref_profiles\n"
    )
    values = parse_storage(output)
    assert {v.name: v.value for v in values}["storage_total"] == 52389356 * 1024
    assert all(value.labels == (("mount", "/data"),) for value in values)


@pytest.mark.parametrize(
    "mount",
    [
        "/system",
        "/database",
        "/data_mirrorx",
        "/dataevil",
        "/data/../system",
        "/data/./user",
        "/data//user",
        "/data/" + "x" * 65,
    ],
)
def test_storage_rejects_unrelated_or_malformed_descendant_paths(mount: str) -> None:
    assert parse_storage(f"/dev/dm 100 50 50 50% {mount}") == ()


def test_network_bounds_preserve_physical_and_active_interfaces_after_virtuals() -> None:
    output = fixture("network_many_interfaces.txt")
    values = parse_network(output)
    assert len(values) == 64
    counters = {(dict(v.labels)["interface"], v.name): v.value for v in values}
    assert counters[("wlan0", "network_receive")] == 123456
    assert counters[("wlan0", "network_transmit")] == 654321
    assert counters[("rmnet_data0", "network_receive")] == 500
    assert counters[("eth0", "network_receive")] == 0
    assert counters[("v4-rmnet0", "network_receive")] == 1000
    assert parse_network("\n".join(reversed(output.splitlines()))) == values


def test_ip_link_interface_bounds_use_same_priority_as_proc() -> None:
    rows = fixture("network_many_interfaces.txt").splitlines()[1:]
    output = ""
    for index, row in enumerate(rows):
        interface, raw = row.split(":", 1)
        fields = raw.split()
        output += (
            f"{index + 1}: {interface}: <UP>\n"
            f" RX: bytes packets errors\n {fields[0]} 0 0\n"
            f" TX: bytes packets errors\n {fields[8]} 0 0\n"
        )
    assert parse_ip_link(output) == parse_network("\n".join(rows))
