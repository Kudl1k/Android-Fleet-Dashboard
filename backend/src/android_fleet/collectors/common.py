"""Small transport-safe helpers shared by independent collectors."""

import math
from datetime import UTC, datetime

from android_fleet.adb.base import AdbClient
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def validate_timeout(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("collector timeout must be finite and positive")
    return timeout


def can_collect(device: Device) -> bool:
    return device.state == DeviceState.ONLINE and DeviceCapability.ADB_SHELL in device.capabilities


async def read_shell(
    adb: AdbClient, serial: str, argv: tuple[str, ...], timeout: float
) -> str | None:
    try:
        result = await adb.shell(serial, argv, timeout=timeout)
    except (OSError, TimeoutError, RuntimeError):
        return None
    return result.stdout if result.exit_code == 0 and not result.timeout else None


async def read_script(adb: AdbClient, device: Device, script: str, timeout: float) -> str | None:
    """Run a read-only script, elevated through su where root was observed.

    Rooted devices can expose sysfs/procfs files that SELinux hides from the shell user.
    A failed or denied su falls back to the unprivileged shell instead of failing.
    """
    if DeviceCapability.ROOT_SHELL in device.capabilities:
        output = await read_shell(adb, device.serial, ("su", "-c", script), timeout)
        if output is not None and output.strip():
            return output
    return await read_shell(adb, device.serial, ("sh", "-c", script), timeout)


def snapshot(device: Device, values: tuple[MetricValue, ...] = ()) -> MetricSnapshot:
    return MetricSnapshot(device.id, datetime.now(UTC), tuple(v for v in values if valid_metric(v)))
