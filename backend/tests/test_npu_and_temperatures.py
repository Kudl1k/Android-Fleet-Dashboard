from datetime import UTC, datetime

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.collectors.npu import NPU_SCRIPT, NpuCollector, parse_npu
from android_fleet.collectors.thermal import THERMAL_SCRIPT, ThermalCollector, parse_thermal
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult
from android_fleet.metrics.exporter import render_metrics
from android_fleet.metrics.models import MetricSnapshot


def test_npu_validates_identity_units_and_never_invents_utilization() -> None:
    values = parse_npu(
        "fdab0000.npu|800000000\nnot-gpu|500\nnpu0|NaN\nnpu1|0\nnpu2|-4\nnpu3|9000000000000"
    )
    assert len(values) == 1
    assert values[0].name == "npu_frequency"
    assert values[0].unit == "hertz"
    assert values[0].value == 800000000
    assert dict(values[0].labels) == {"accelerator": "fdab0000.npu"}
    device = Device("phone", "serial", "Phone", DeviceState.ONLINE)
    output = render_metrics(
        [device], {device.id: MetricSnapshot(device.id, datetime.now(UTC), values)}
    )
    assert b'android_npu_frequency_hz{accelerator="fdab0000.npu",device_id="phone"}' in output


@pytest.mark.parametrize("rooted", [False, True])
async def test_npu_capability_and_denied_sources(rooted: bool) -> None:
    class Adb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
        ) -> CommandResult:
            self.calls.append((serial, argv))
            if argv[-1] == NPU_SCRIPT:
                return CommandResult(stdout="npu0|400000000")
            return CommandResult(exit_code=1)

    adb = Adb()
    capabilities = {DeviceCapability.ADB_SHELL}
    if rooted:
        capabilities.add(DeviceCapability.ROOT_SHELL)
    device = Device("phone", "serial", "Phone", DeviceState.ONLINE, capabilities=capabilities)
    assert (await NpuCollector().collect(device, adb)).values
    assert DeviceCapability.NPU_METRICS in device.capabilities
    assert adb.calls[0][1][:2] == (("su", "-c") if rooted else ("sh", "-c"))
    device.state = DeviceState.OFFLINE
    assert not (await NpuCollector().collect(device, adb)).values
    assert not parse_npu("Permission denied")


async def test_thermal_includes_sysfs_even_when_hal_is_available() -> None:
    class Adb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10
        ) -> CommandResult:
            if argv == ("dumpsys", "thermalservice"):
                return CommandResult(
                    stdout=(
                        "Current temperatures from HAL:\n"
                        " Temperature{mValue=40, mType=0, mName=CPU}"
                    )
                )
            if argv[-1] == THERMAL_SCRIPT:
                return CommandResult(
                    stdout="thermal_zone0|gpu|42000\nthermal_zone1|bcl_current|90000\nthermal_zone2|npu|43000"
                )
            return CommandResult(exit_code=1)

    device = Device(
        "phone", "serial", "Phone", DeviceState.ONLINE, capabilities={DeviceCapability.ADB_SHELL}
    )
    values = (await ThermalCollector().collect(device, Adb())).values
    assert {dict(value.labels)["type"] for value in values} == {"cpu", "gpu", "npu"}
    output = "Current temperatures from HAL:\n" + "\n".join(
        f"Temperature{{mValue=40, mType=0, mName=cpu{i}}}" for i in range(160)
    )
    assert len(parse_thermal(output)) == 128
