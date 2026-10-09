from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ConnectionType(StrEnum):
    ADB_TCP = "adb_tcp"
    WIRELESS_ADB = "wireless_adb"
    USB = "usb"


class DeviceState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    PAIRING_REQUIRED = "pairing_required"
    ADB_UNAVAILABLE = "adb_unavailable"
    ERROR = "error"


class DeviceCapability(StrEnum):
    ADB_SHELL = "adb_shell"
    ROOT_SHELL = "root_shell"
    CPU_METRICS = "cpu_metrics"
    MEMORY_METRICS = "memory_metrics"
    BATTERY_METRICS = "battery_metrics"
    STORAGE_METRICS = "storage_metrics"
    NETWORK_METRICS = "network_metrics"
    UPTIME_METRICS = "uptime_metrics"
    THERMAL_BASIC = "thermal_basic"
    THERMAL_FULL = "thermal_full"
    GPU_METRICS = "gpu_metrics"
    NPU_METRICS = "npu_metrics"
    PROCESS_LIST = "process_list"
    PROCESS_CONTROL = "process_control"
    PACKAGE_MANAGEMENT = "package_management"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_ROOT = "file_root"
    LOGCAT = "logcat"
    BINARY_EXECUTION = "binary_execution"
    REBOOT = "reboot"


@dataclass
class Device:
    id: str
    serial: str
    name: str
    state: DeviceState
    connection_type: ConnectionType = ConnectionType.USB
    manufacturer: str | None = None
    model: str | None = None
    android_version: str | None = None
    sdk: int | None = None
    abi: str | None = None
    soc: str | None = None
    root_available: bool | None = None
    capabilities: set[DeviceCapability] = field(default_factory=set)
    last_seen: datetime | None = None
