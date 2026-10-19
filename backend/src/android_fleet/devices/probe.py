import re
from datetime import UTC, datetime

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.battery import parse_battery
from android_fleet.collectors.memory import parse_memory
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.execution.models import CommandResult


def parse_getprop(output: str) -> dict[str, str]:
    """Ignore unsupported/malformed lines without assuming property availability."""
    return dict(re.findall(r"^\[([^\]\n]+)\]: \[([^\]\n]*)\]$", output, re.MULTILINE))


class DeviceProbe:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

    async def _shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        try:
            return await self.adb.shell(serial, argv, timeout=timeout)
        except (OSError, TimeoutError, RuntimeError):
            return CommandResult(exit_code=None, timeout=True)

    async def probe(self, device: Device) -> Device:
        device.capabilities.clear()
        device.root_available = None
        device.manufacturer = None
        device.model = None
        device.android_version = None
        device.abi = None
        device.soc = None
        device.kernel = None
        device.sdk = None
        if device.state != DeviceState.ONLINE:
            return device
        properties = await self._shell(device.serial, ("getprop",))
        if properties.exit_code != 0 or properties.timeout:
            device.state = DeviceState.ERROR
            return device
        device.capabilities.add(DeviceCapability.ADB_SHELL)
        device.last_seen = datetime.now(UTC)
        values = parse_getprop(properties.stdout)
        device.manufacturer = values.get("ro.product.manufacturer")
        device.model = values.get("ro.product.model")
        device.android_version = values.get("ro.build.version.release")
        device.abi = values.get("ro.product.cpu.abi")
        # ro.soc.model exists since Android 12; older builds expose only the board platform.
        device.soc = values.get("ro.soc.model") or values.get("ro.board.platform")
        sdk = values.get("ro.build.version.sdk", "")
        device.sdk = int(sdk) if len(sdk) <= 5 and sdk.isascii() and sdk.isdecimal() else None
        kernel = await self._shell(device.serial, ("uname", "-r"), timeout=2.0)
        if kernel.exit_code == 0 and not kernel.timeout:
            release = kernel.stdout.strip()
            if release and len(release) <= 128 and release.isprintable():
                device.kernel = release
        direct = await self._shell(device.serial, ("id", "-u"), timeout=2.0)
        if direct.exit_code == 0 and not direct.timeout and direct.stdout.strip() == "0":
            device.root_available = True
        else:
            elevated = await self._shell(device.serial, ("su", "-c", "id -u"), timeout=2.0)
            if elevated.exit_code == 0 and not elevated.timeout:
                uid = elevated.stdout.strip()
                if uid.isascii() and uid.isdecimal() and len(uid) <= 10:
                    device.root_available = uid == "0"
            elif not elevated.timeout and elevated.exit_code in {1, 127}:
                # Explicit permission denial or missing su is a negative observation.
                message = elevated.stderr.lower()
                if any(
                    marker in message
                    for marker in ("permission denied", "not found", "unavailable", "not allowed")
                ):
                    device.root_available = False
        if device.root_available is True:
            device.capabilities.add(DeviceCapability.ROOT_SHELL)
        battery = await self._shell(device.serial, ("dumpsys", "battery"))
        memory = await self._shell(device.serial, ("cat", "/proc/meminfo"))
        if battery.exit_code == 0 and not battery.timeout and parse_battery(battery.stdout):
            device.capabilities.add(DeviceCapability.BATTERY_METRICS)
        if memory.exit_code == 0 and not memory.timeout and parse_memory(memory.stdout):
            device.capabilities.add(DeviceCapability.MEMORY_METRICS)
        return device
