"""Root-aware ZRAM, CPU frequency ceiling, vendor GPU and process collectors."""

from datetime import UTC, datetime

from prometheus_client.parser import text_string_to_metric_families

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.collectors.battery import (
    CAPACITY_SCRIPT,
    BatteryCollector,
    parse_battery,
    parse_battery_capacity,
)
from android_fleet.collectors.cpu_limits import CpuLimitsCollector, parse_cpu_limits
from android_fleet.collectors.gpu import GPU_SCRIPT, GpuCollector, parse_gpu
from android_fleet.collectors.processes import (
    PROCESS_SCRIPT,
    ProcessCollector,
    parse_processes,
    process_metrics,
)
from android_fleet.collectors.zram import ZramCollector, parse_zram
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.devices.probe import DeviceProbe
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.collection import MetricPipeline
from android_fleet.metrics.exporter import render_metrics
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def device(serial: str, *, rooted: bool) -> Device:
    capabilities = {DeviceCapability.ADB_SHELL}
    if rooted:
        capabilities.add(DeviceCapability.ROOT_SHELL)
    return Device(serial, serial, serial, DeviceState.ONLINE, capabilities=capabilities)


def by_name(values: tuple[MetricValue, ...]) -> dict[str, float]:
    return {value.name: value.value for value in values if not value.labels}


def test_zram_sums_configured_devices_and_supports_legacy_kernels() -> None:
    output = (
        "zram0 2147483648 805306368 268435456 285212672\n"
        "zram1 0 0 0 0\n"  # unconfigured device is not an empty swap
        "zram2 1073741824 100 50 60\n"
    )
    assert by_name(parse_zram(output)) == {
        "zram_disk_size": 3221225472.0,
        "zram_original_data": 805306468.0,
        "zram_compressed_data": 268435506.0,
        "zram_memory_used": 285212732.0,
    }
    # A device with a missing counter drops that total rather than inventing zero.
    assert by_name(parse_zram("zram0 1024 10 5\n")) == {
        "zram_disk_size": 1024.0,
        "zram_original_data": 10.0,
        "zram_compressed_data": 5.0,
    }
    assert parse_zram("") == ()
    assert parse_zram("zram0 0 0 0 0\n") == ()
    assert parse_zram("zram0 ??? x y z\n") == ()


def test_cpu_limits_expose_hardware_maximum_policy_limit_and_cap() -> None:
    values = parse_cpu_limits("0 1708800 1708800\n6 1996800 1612800\n7 bad 1\n")
    limits = {(v.name, dict(v.labels).get("core")): v.value for v in values}
    assert limits[("cpu_max_frequency", "6")] == 1_996_800_000
    assert limits[("cpu_frequency_limit", "6")] == 1_612_800_000
    assert limits[("cpu_frequency_capped", None)] == 1
    assert ("cpu_max_frequency", "7") not in limits
    assert by_name(parse_cpu_limits("0 1708800 1708800\n"))["cpu_frequency_capped"] == 0
    assert parse_cpu_limits("garbage\n") == ()


def test_adreno_gpu_prefers_busy_percentage_and_falls_back_to_window() -> None:
    vendor, values = parse_gpu(
        "vendor=adreno\nbusy_percent=37 %\ngpubusy=1 2\ncur_hz=504000000\nmax_hz=780000000\n"
    )
    assert vendor == "adreno"
    assert by_name(values) == {
        "gpu_usage": 0.37,
        "gpu_frequency": 504_000_000,
        "gpu_max_frequency": 780_000_000,
    }
    _, window = parse_gpu("vendor=adreno\ngpubusy=  2500  10000\n")
    assert by_name(window) == {"gpu_usage": 0.25}
    _, idle_window = parse_gpu("vendor=adreno\ngpubusy=0 0\n")
    assert idle_window == ()


def test_mali_gpu_converts_kilohertz_and_unknown_vendor_is_unsupported() -> None:
    vendor, values = parse_gpu("vendor=mali\nutilization=12\ncur_khz=150000\nmax_khz=940000\n")
    assert vendor == "mali"
    assert by_name(values) == {
        "gpu_usage": 0.12,
        "gpu_frequency": 150_000_000,
        "gpu_max_frequency": 940_000_000,
    }
    assert parse_gpu("vendor=powervr\nutilization=50\n") == (None, ())
    assert parse_gpu("") == (None, ())
    _, invalid = parse_gpu("vendor=adreno\nbusy_percent=250\ncur_hz=-1\n")
    assert invalid == ()


def test_process_parser_handles_spaces_in_comm_and_prefers_full_name() -> None:
    output = (
        "1450 (ndroid.systemui) S 1 1 0 0 -1 0 0 0 0 0 100 20 0 0 20 0 1 0 340 1 3 0"
        "\tcom.android.systemui\n"
        "77 (my (odd) name) R 1 1 0 0 -1 0 0 0 0 0 5 5 0 0 20 0 1 0 9 1 2 0\t\n"
        "88 (sh) S 1 1 0 0 -1 0 0 0 0 0 1 1 0 0 20 0 1 0 9 1 2 0\t/bin/unrelated\n"
        "1084 (main) S 1 1084 0 0 -1 0 0 0 0 0 3936 7156 0 0 20 0 6 0 1077 1 4361 0\tzygote64\n"
        "garbage line\n"
        "99 (short) S 1\n"
    )
    processes = parse_processes(output)
    assert processes[1450] == ("com.android.systemui", 120, 340, 3 * 4096)
    assert processes[77][0] == "my__odd__name"
    assert processes[88][0] == "sh"
    assert processes[1084][0] == "zygote64"
    assert set(processes) == {1450, 77, 88, 1084}


def test_battery_capacity_converts_microampere_hours_and_skips_unsupported() -> None:
    assert by_name(parse_battery_capacity("charge_full=3000000\ncycle_count=412\n")) == {
        "battery_charge_full": 3.0,
        "battery_cycle_count": 412,
    }
    # 0 is the "unsupported" sentinel of many fuel gauges, not an empty battery.
    assert parse_battery_capacity("charge_full=0\ncharge_full_design=x\ncycle_count=-1\n") == ()
    # Pixel 3a XL dumpsys battery reports the remaining charge in microampere-hours.
    charge = by_name(parse_battery("level: 78\nscale: 100\nCharge counter: 2887741\n"))
    assert charge["battery_charge"] == 2.887741
    assert "battery_charge" not in by_name(parse_battery("level: 1\nscale: 1\nCharge counter: 0\n"))


async def test_battery_capacity_uses_su_on_rooted_devices_only() -> None:
    adb = FakeAdbClient()
    adb.devices["pixel-stock"] = DeviceState.ONLINE
    rooted = device("pixel-rooted", rooted=True)
    stock = device("pixel-stock", rooted=False)
    for target in (rooted, stock):
        target.capabilities.add(DeviceCapability.BATTERY_METRICS)
    rooted_values = by_name((await BatteryCollector().collect(rooted, adb)).values)
    assert rooted_values["battery_charge_full_design"] == 3.7
    assert rooted_values["battery_cycle_count"] == 412
    assert ("pixel-rooted", ("su", "-c", CAPACITY_SCRIPT)) in adb.calls
    stock_values = by_name((await BatteryCollector().collect(stock, adb)).values)
    assert "battery_charge_full" not in stock_values
    assert stock_values["battery_charge"] == 2.25


def test_parsers_accept_outputs_captured_on_lab_pixel_3a_xl() -> None:
    """Root-shell outputs recorded on the lab Pixel 3a XL (SDM670, Android 12, kernel 4.9)."""
    vendor, gpu = parse_gpu(
        "vendor=adreno\nbusy_percent=11 %\ngpubusy=0       0\ncur_hz=180000000\nmax_hz=430000000\n"
    )
    assert vendor == "adreno"
    assert by_name(gpu) == {"gpu_usage": 0.11, "gpu_frequency": 180e6, "gpu_max_frequency": 430e6}
    assert by_name(parse_zram("zram0 2147483648 865091584 127954897 134397952\n")) == {
        "zram_disk_size": 2147483648,
        "zram_original_data": 865091584,
        "zram_compressed_data": 127954897,
        "zram_memory_used": 134397952,
    }
    limits = "".join(f"{core} 1708800 1708800\n" for core in range(6))
    limits += "6 1996800 1996800\n7 1996800 1996800\n"
    values = parse_cpu_limits(limits)
    assert by_name(values)["cpu_frequency_capped"] == 0
    assert len([v for v in values if v.name == "cpu_max_frequency"]) == 8


def test_process_cpu_is_delta_in_cores_and_ignores_reused_pids() -> None:
    first = {1: ("a", 100, 10, 4096), 2: ("b", 50, 20, 8192), 3: ("c", 10, 30, 1)}
    second = {1: ("a", 400, 10, 4096), 2: ("b", 60, 20, 8192), 3: ("new", 900, 99, 1)}
    baseline = process_metrics(None, first, None)
    assert by_name(baseline) == {"process_count": 3}
    assert not any(v.name == "process_cpu" for v in baseline)
    values = process_metrics(first, second, 2.0)
    cpu = {dict(v.labels)["process"]: v.value for v in values if v.name == "process_cpu"}
    assert cpu == {"a": 1.5, "b": 0.05}
    memory = [dict(v.labels)["process"] for v in values if v.name == "process_memory"]
    assert memory == ["b", "a", "new"]
    assert all(valid_metric(v) for v in values)
    assert process_metrics(None, {}, None) == ()


async def test_rooted_device_reads_vendor_sources_through_su() -> None:
    adb = FakeAdbClient()
    rooted = device("pixel-rooted", rooted=True)
    gpu = await GpuCollector().collect(rooted, adb)
    zram = await ZramCollector().collect(rooted, adb)
    limits = await CpuLimitsCollector().collect(rooted, adb)
    assert by_name(gpu.values)["gpu_usage"] == 0.37
    assert by_name(zram.values)["zram_disk_size"] == 2147483648
    assert by_name(limits.values)["cpu_frequency_capped"] == 1
    assert DeviceCapability.GPU_METRICS in rooted.capabilities
    assert ("pixel-rooted", ("su", "-c", GPU_SCRIPT)) in adb.calls


async def test_stock_device_never_uses_su_and_reports_absent_root_only_metrics() -> None:
    adb = FakeAdbClient()
    stock = device("pixel-stock", rooted=False)
    assert (await GpuCollector().collect(stock, adb)).values == ()
    assert (await ZramCollector().collect(stock, adb)).values == ()
    assert (await ProcessCollector().collect(stock, adb)).values == ()
    # CPU ceilings are world-readable sysfs and stay available without root.
    assert (await CpuLimitsCollector().collect(stock, adb)).values
    assert not any(argv[0] == "su" for _, argv in adb.calls)
    assert DeviceCapability.GPU_METRICS not in stock.capabilities


async def test_failed_su_falls_back_to_unprivileged_shell() -> None:
    adb = FakeAdbClient()
    # Root was observed earlier but su is now denied (for example revoked in Magisk).
    stale = device("pixel-stock", rooted=True)
    snapshot = await CpuLimitsCollector().collect(stale, adb)
    assert snapshot.values
    assert [argv[0] for _, argv in adb.calls] == ["su", "sh"]


async def test_process_collector_establishes_baseline_then_reports_top_consumers() -> None:
    adb = FakeAdbClient()
    rooted = device("pixel-rooted", rooted=True)
    ticks = iter(range(0, 3000, 30))
    collector = ProcessCollector(clock=lambda: float(next(ticks)))
    first = await collector.collect(rooted, adb)
    assert by_name(first.values) == {"process_count": 4}
    second = await collector.collect(rooted, adb)
    names = {dict(v.labels)["process"] for v in second.values if v.name == "process_cpu"}
    assert names == {"surfaceflinger", "com.android.systemui"}
    assert ("pixel-rooted", ("su", "-c", PROCESS_SCRIPT)) in adb.calls
    offline = Device("pixel-rooted", "pixel-rooted", "x", DeviceState.OFFLINE)
    assert (await collector.collect(offline, adb)).values == ()
    # Offline resets the baseline: the next online poll cannot invent CPU deltas.
    third = await collector.collect(rooted, adb)
    assert not any(v.name == "process_cpu" for v in third.values)


async def test_pipeline_and_probe_feed_device_info_and_new_families() -> None:
    adb = FakeAdbClient()
    rooted = await DeviceProbe(adb).probe(
        Device("pixel-rooted", "pixel-rooted", "Rooted", DeviceState.ONLINE)
    )
    assert rooted.kernel == "4.9.292-demo"
    assert rooted.soc == "SDM670"
    pipeline = MetricPipeline()
    await pipeline.collect(rooted, adb)
    snapshot = await pipeline.collect(rooted, adb)
    output = render_metrics([rooted], {rooted.id: snapshot}).decode()
    families = {family.name: family for family in text_string_to_metric_families(output)}
    info = families["android_device_info"].samples[0]
    assert info.labels == {
        "device_id": "pixel-rooted",
        "manufacturer": "Google",
        "model": "Pixel demo",
        "android_version": "15",
        "soc": "SDM670",
        "kernel": "4.9.292-demo",
    }
    assert info.value == 1
    for name in (
        "android_gpu_usage_ratio",
        "android_zram_disk_size_bytes",
        "android_cpu_frequency_capped",
        "android_process_count",
        "android_process_memory_bytes",
    ):
        assert families[name].samples, name


def test_device_info_sanitizes_values_and_skips_unprobed_devices() -> None:
    now = datetime.now(UTC)
    probed = Device("a", "a", "A", DeviceState.ONLINE, model="Pixel\n3a" + "x" * 100, last_seen=now)
    unprobed = Device("b", "b", "B", DeviceState.OFFLINE)
    output = render_metrics([probed, unprobed], {"a": MetricSnapshot("a", now)}).decode()
    families = {family.name: family for family in text_string_to_metric_families(output)}
    samples = families["android_device_info"].samples
    assert [sample.labels["device_id"] for sample in samples] == ["a"]
    assert samples[0].labels["model"].startswith("Pixel_3a")
    assert len(samples[0].labels["model"]) == 64
