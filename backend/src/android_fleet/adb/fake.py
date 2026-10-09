"""Deterministic, deliberately varied demo transports; no device is contacted."""

from android_fleet.collectors.cpu import FREQUENCY_SCRIPT
from android_fleet.collectors.thermal import THERMAL_SCRIPT
from android_fleet.devices.models import DeviceState
from android_fleet.discovery.models import MdnsService
from android_fleet.execution.models import CommandResult

BATTERY_OUTPUT = "level: 75\nscale: 100\ntemperature: 285\nvoltage: 4100\n"
MEMORY_OUTPUT = (
    "MemTotal:        8000000 kB\nMemAvailable:    3000000 kB\n"
    "SwapTotal:       2000000 kB\nSwapFree:        1000000 kB\n"
)
GETPROP_OUTPUT = """[ro.product.manufacturer]: [Google]
[ro.product.model]: [Pixel demo]
[ro.build.version.release]: [15]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.build.version.sdk]: [35]
"""


class FakeAdbClient:
    def __init__(self) -> None:
        self.devices = {
            "pixel-rooted": DeviceState.ONLINE,
            "pixel-stock": DeviceState.ONLINE,
            "pixel-offline": DeviceState.OFFLINE,
            "pixel-malformed": DeviceState.ONLINE,
        }
        self.endpoints: dict[str, DeviceState] = {}
        self.services: tuple[MdnsService, ...] = ()
        self.connection_calls: list[str] = []
        self.disconnection_calls: list[str] = []
        self.cpu_samples: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def list_devices(self) -> dict[str, DeviceState]:
        return dict(self.devices)

    async def shell(
        self,
        serial: str,
        argv: tuple[str, ...],
        *,
        timeout: float = 10.0,
    ) -> CommandResult:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.calls.append((serial, argv))
        if self.devices.get(serial) != DeviceState.ONLINE:
            return CommandResult(stderr="device offline", exit_code=1)
        if argv[:3] == ("pm", "list", "packages"):
            return CommandResult(stdout="package:com.example.demo\n")
        if argv[:2] == ("dumpsys", "package"):
            return CommandResult(stdout="versionName=1.0\nversionCode=1 minSdk=23 targetSdk=35\n")
        if argv[:1] == ("getprop",) and len(argv) == 2:
            return CommandResult(stdout="demo\n")
        if argv[:2] in {("input", "keyevent"), ("am", "force-stop"), ("monkey", "-p")}:
            return CommandResult(stdout="Success\n")
        if argv == ("getprop",):
            return CommandResult(stdout=GETPROP_OUTPUT)
        if argv == ("id", "-u"):
            return CommandResult(stdout="2000\n")
        if argv == ("su", "-c", "id -u"):
            if serial == "pixel-rooted":
                return CommandResult(stdout="0\n")
            return CommandResult(stderr="su: unavailable", exit_code=1)
        if argv == ("dumpsys", "battery"):
            return CommandResult(
                stdout="level: ???\n" if serial == "pixel-malformed" else BATTERY_OUTPUT
            )
        if argv == ("cat", "/proc/meminfo"):
            return CommandResult(
                stdout="MemTotal: ??? kB\n" if serial == "pixel-malformed" else MEMORY_OUTPUT
            )
        if argv == ("cat", "/proc/stat"):
            if serial == "pixel-malformed":
                return CommandResult(stdout="cpu ??? invalid\n")
            step = self.cpu_samples.get(serial, 0)
            self.cpu_samples[serial] = step + 1
            return CommandResult(
                stdout=(
                    f"cpu {100 + step * 40} 10 {50 + step * 20} {1000 + step * 60} 10 5 5 0\n"
                    f"cpu0 {50 + step * 20} 5 {25 + step * 10} {500 + step * 30} 5 2 3 0\n"
                    f"cpu1 {50 + step * 20} 5 {25 + step * 10} {500 + step * 30} 5 3 2 0\n"
                )
            )
        outputs = {
            ("dumpsys", "cpuinfo"): "12.5% TOTAL: 7.5% user + 5% kernel\n",
            ("sh", "-c", FREQUENCY_SCRIPT): "0 1800000\n1 2000000\n",
            (
                "df",
                "-k",
                "/data",
            ): (
                "Filesystem 1K-blocks Used Available Use% Mounted on\n"
                "/dev/dm-10 10000000 7000000 3000000 70% /data\n"
            ),
            ("cat", "/proc/net/dev"): "wlan0: 123456 12 0 0 0 0 0 0 654321 21 0 0 0 0 0 0\n",
            (
                "ip",
                "-s",
                "link",
            ): (
                "2: wlan0: <UP>\n RX: bytes packets errors\n 123456 12 0\n"
                " TX: bytes packets errors\n 654321 21 0\n"
            ),
            ("cat", "/proc/uptime"): "12345.67 67890.12\n",
            (
                "dumpsys",
                "thermalservice",
            ): (
                "Thermal Status: 0\nCurrent temperatures from HAL:\n"
                " Temperature{mValue=44.5, mType=0, mName=CPU, mStatus=0}\n"
            ),
            ("sh", "-c", THERMAL_SCRIPT): "thermal_zone0|cpu-0|44500\n",
            ("cat", "/sys/class/power_supply/battery/current_now"): "-500000\n",
        }
        if argv in outputs:
            return CommandResult(
                stdout="unsupported ???\n" if serial == "pixel-malformed" else outputs[argv]
            )
        return CommandResult(stderr="unsupported fake command", exit_code=1)

    async def command(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 30.0
    ) -> CommandResult:
        self.calls.append((serial, argv))
        if self.devices.get(serial) != DeviceState.ONLINE:
            return CommandResult(exit_code=1)
        return CommandResult(stdout="Success\n")

    async def screenshot(
        self, serial: str, *, timeout: float = 30.0, max_bytes: int = 16777216
    ) -> bytes:
        import base64

        if self.devices.get(serial) != DeviceState.ONLINE:
            raise RuntimeError("Device offline")
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

    async def connect(self, address: str) -> CommandResult:
        self.connection_calls.append(address)
        state = self.endpoints.get(address)
        if state is None:
            return CommandResult(stderr="connection refused", exit_code=1)
        self.devices[address] = state
        return CommandResult(stdout=f"connected to {address}\n")

    async def disconnect(self, address: str) -> CommandResult:
        self.disconnection_calls.append(address)
        self.devices.pop(address, None)
        return CommandResult(stdout=f"disconnected {address}\n")

    async def mdns_services(self) -> tuple[MdnsService, ...]:
        return self.services
