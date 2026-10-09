from dataclasses import dataclass

from android_fleet.devices.models import DeviceState


@dataclass(frozen=True)
class ConnectionObservation:
    device_id: str
    state: DeviceState
    serial: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_in_seconds: float | None = None
