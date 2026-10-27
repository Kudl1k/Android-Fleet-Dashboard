"""Public battery service values and optional signed sysfs current readings."""

import math

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import read_script, read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability, DeviceState
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

# Fuel-gauge capacity in microampere-hours plus the cycle counter. These files are
# commonly hidden from the shell user, so the script runs through su where available.
CAPACITY_SCRIPT = """b=/sys/class/power_supply/battery
for f in charge_full charge_full_design cycle_count; do
 [ -r "$b/$f" ] && printf '%s=%s\\n' "$f" "$(cat "$b/$f")"
done 2>/dev/null"""
_CAPACITY_NAMES = {
    "charge_full": "battery_charge_full",
    "charge_full_design": "battery_charge_full_design",
}
_FIELDS = {"level", "scale", "temperature", "voltage", "status", "health", "Charge counter"}


def parse_battery(output: str) -> tuple[MetricValue, ...]:
    fields: dict[str, float] = {}
    for line in output.splitlines():
        key, separator, raw = line.strip().partition(":")
        if separator and key in _FIELDS:
            try:
                value = float(raw.strip())
            except ValueError:
                continue
            if math.isfinite(value):
                fields[key] = value
    values: list[MetricValue] = []
    level, scale = fields.get("level"), fields.get("scale")
    if level is not None and scale is not None and scale > 0 and 0 <= level <= scale:
        values.append(MetricValue("battery_level", level / scale, "ratio"))
    if "temperature" in fields:
        values.append(MetricValue("battery_temperature", fields["temperature"] / 10, "celsius"))
    if "voltage" in fields:
        values.append(MetricValue("battery_voltage", fields["voltage"] / 1000, "volts"))
    status = fields.get("status")
    if status is not None and status.is_integer() and 1 <= status <= 5:
        values.append(MetricValue("battery_status", status, "level"))
        if status != 1:  # BATTERY_STATUS_UNKNOWN does not establish charging intent.
            values.append(MetricValue("battery_charging", float(status == 2), "boolean"))
    health = fields.get("health")
    if health is not None and health.is_integer() and 1 <= health <= 7:
        values.append(MetricValue("battery_health", health, "level"))
    # Charge counter is the remaining charge in microampere-hours; 0 means unsupported.
    charge = fields.get("Charge counter")
    if charge is not None and charge > 0:
        values.append(MetricValue("battery_charge", charge / 1_000_000, "ampere_hours"))
    return tuple(value for value in values if valid_metric(value))


def parse_battery_capacity(output: str) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = []
    for line in output.splitlines()[:8]:
        key, _, raw = line.strip().partition("=")
        try:
            number = int(raw.strip())
        except ValueError:
            continue
        if key in _CAPACITY_NAMES and number > 0:
            values.append(MetricValue(_CAPACITY_NAMES[key], number / 1_000_000, "ampere_hours"))
        elif key == "cycle_count" and number >= 0:
            values.append(MetricValue("battery_cycle_count", float(number), "count"))
    capacities = {value.name: value.value for value in values}
    full = capacities.get("battery_charge_full")
    design = capacities.get("battery_charge_full_design")
    # Some vendor drivers (seen on a Samsung Galaxy A14) expose the design value in a
    # different unit. A design capacity under half the measured one is contradictory,
    # so withhold it rather than guess a conversion.
    if full is not None and design is not None and design < full / 2:
        values = [value for value in values if value.name != "battery_charge_full_design"]
    return tuple(value for value in values if valid_metric(value))


def parse_battery_current(output: str) -> tuple[MetricValue, ...]:
    try:
        value = MetricValue("battery_current", float(output.strip()) / 1_000_000, "amperes")
    except ValueError:
        return ()
    return (value,) if valid_metric(value) else ()


class BatteryCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if (
            device.state != DeviceState.ONLINE
            or DeviceCapability.BATTERY_METRICS not in device.capabilities
        ):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("dumpsys", "battery"), self._timeout)
        values = parse_battery(output) if output is not None else ()
        # current_now is microamperes, signed according to the device driver.
        current = await read_shell(
            adb,
            device.serial,
            ("cat", "/sys/class/power_supply/battery/current_now"),
            self._timeout,
        )
        if current is not None:
            values += parse_battery_current(current)
        capacity = await read_script(adb, device, CAPACITY_SCRIPT, self._timeout)
        if capacity is not None:
            values += parse_battery_capacity(capacity)
        return snapshot(device, values)
