from android_fleet.adb.fake import FakeAdbClient
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.devices.probe import DeviceProbe, parse_getprop


def test_parse_properties_ignores_malformed() -> None:
    assert parse_getprop("bad\n[ro.product.model]: [Pixel]\n") == {"ro.product.model": "Pixel"}


async def test_probe_root_and_stock() -> None:
    adb = FakeAdbClient()
    for serial, rooted in (("pixel-rooted", True), ("pixel-stock", False)):
        device = Device(serial, serial, serial, DeviceState.ONLINE)
        await DeviceProbe(adb).probe(device)
        assert device.model == "Pixel demo"
        assert device.sdk == 35
        assert device.root_available is rooted
        assert (DeviceCapability.ROOT_SHELL in device.capabilities) is rooted
        assert DeviceCapability.BATTERY_METRICS in device.capabilities


async def test_malformed_metrics_do_not_grant_capabilities() -> None:
    device = Device("pixel-malformed", "pixel-malformed", "demo", DeviceState.ONLINE)
    await DeviceProbe(FakeAdbClient()).probe(device)
    assert DeviceCapability.MEMORY_METRICS not in device.capabilities
    assert DeviceCapability.BATTERY_METRICS not in device.capabilities


async def test_root_probe_timeout_remains_unknown() -> None:
    from android_fleet.execution.models import CommandResult

    class TimeoutRootAdb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if argv == ("su", "-c", "id -u"):
                assert timeout == 2.0
                return CommandResult(exit_code=None, timeout=True)
            return await super().shell(serial, argv, timeout=timeout)

    device = Device("pixel-stock", "pixel-stock", "demo", DeviceState.ONLINE)
    await DeviceProbe(TimeoutRootAdb()).probe(device)
    assert device.root_available is None
    assert DeviceCapability.ROOT_SHELL not in device.capabilities


async def test_reprobe_clears_root_and_isolates_failed_observations() -> None:
    from android_fleet.execution.models import CommandResult

    class FlakyAdb(FakeAdbClient):
        fail = False

        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if self.fail and argv in {("su", "-c", "id -u"), ("dumpsys", "battery")}:
                raise OSError("transient failure")
            return await super().shell(serial, argv, timeout=timeout)

    adb = FlakyAdb()
    device = Device("pixel-rooted", "pixel-rooted", "demo", DeviceState.ONLINE)
    await DeviceProbe(adb).probe(device)
    assert device.root_available is True
    adb.fail = True
    await DeviceProbe(adb).probe(device)
    assert device.root_available is None
    assert DeviceCapability.ROOT_SHELL not in device.capabilities
    assert DeviceCapability.BATTERY_METRICS not in device.capabilities
    assert DeviceCapability.MEMORY_METRICS in device.capabilities


async def test_failed_getprop_marks_device_error() -> None:
    device = Device("pixel-offline", "pixel-offline", "demo", DeviceState.ONLINE)
    await DeviceProbe(FakeAdbClient()).probe(device)
    assert device.state == DeviceState.ERROR
    assert not device.capabilities


async def test_oversized_sdk_is_ignored() -> None:
    from android_fleet.execution.models import CommandResult

    class MalformedSdkAdb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if argv == ("getprop",):
                return CommandResult(stdout="[ro.build.version.sdk]: [" + "9" * 5000 + "]\n")
            return await super().shell(serial, argv, timeout=timeout)

    device = Device("pixel-stock", "pixel-stock", "demo", DeviceState.ONLINE)
    await DeviceProbe(MalformedSdkAdb()).probe(device)
    assert device.sdk is None
    assert DeviceCapability.MEMORY_METRICS in device.capabilities


async def test_offline_probe_clears_stale_observations_without_shell() -> None:
    adb = FakeAdbClient()
    device = Device(
        "pixel-offline",
        "pixel-offline",
        "demo",
        DeviceState.OFFLINE,
        root_available=True,
        model="Old model",
        capabilities={DeviceCapability.ROOT_SHELL},
    )
    await DeviceProbe(adb).probe(device)
    assert device.state == DeviceState.OFFLINE
    assert device.root_available is None
    assert device.model is None
    assert not device.capabilities
    assert not adb.calls


async def test_unexpected_root_output_remains_unknown() -> None:
    from android_fleet.execution.models import CommandResult

    class AmbiguousRootAdb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if argv == ("su", "-c", "id -u"):
                assert timeout == 2.0
                return CommandResult(stdout="Please authorize this request", exit_code=0)
            return await super().shell(serial, argv, timeout=timeout)

    device = Device("pixel-stock", "pixel-stock", "demo", DeviceState.ONLINE)
    await DeviceProbe(AmbiguousRootAdb()).probe(device)
    assert device.root_available is None
    assert DeviceCapability.ROOT_SHELL not in device.capabilities


async def test_permission_denied_metric_does_not_grant_capability() -> None:
    from android_fleet.execution.models import CommandResult

    class RestrictedAdb(FakeAdbClient):
        async def shell(
            self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
        ) -> CommandResult:
            if argv == ("cat", "/proc/meminfo"):
                return CommandResult(stderr="Permission denied", exit_code=1)
            return await super().shell(serial, argv, timeout=timeout)

    device = Device("pixel-stock", "pixel-stock", "demo", DeviceState.ONLINE)
    await DeviceProbe(RestrictedAdb()).probe(device)
    assert DeviceCapability.MEMORY_METRICS not in device.capabilities
    assert DeviceCapability.BATTERY_METRICS in device.capabilities
