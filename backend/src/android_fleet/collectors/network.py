"""Raw byte counters, bounded to 32 interfaces; no interval rates are invented."""

import re

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_shell, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue


def _counters(interface: str, receive: str, transmit: str) -> tuple[MetricValue, ...]:
    if interface == "lo":
        return ()
    if any(
        not value.isascii() or not value.isdecimal() or len(value) > 20
        for value in (receive, transmit)
    ):
        return ()
    rx, tx = int(receive), int(transmit)
    if rx > 2**64 - 1 or tx > 2**64 - 1:
        return ()
    values = (
        MetricValue("network_receive", float(rx), "bytes", (("interface", interface),)),
        MetricValue("network_transmit", float(tx), "bytes", (("interface", interface),)),
    )
    return values if all(valid_metric(value) for value in values) else ()


def _rank(interface: str, values: tuple[MetricValue, ...]) -> tuple[int, bool, int, str]:
    groups = (r"wlan[0-9]+", r"eth[0-9]+", r"rmnet(?:_data)?[0-9]+")
    priority = next((i for i, pattern in enumerate(groups) if re.fullmatch(pattern, interface)), 3)
    traffic_observed = any(value.value > 0 for value in values)
    return (int(priority == 3), not traffic_observed, priority, interface)


def _retain(
    interfaces: dict[str, tuple[MetricValue, ...]], interface: str, values: tuple[MetricValue, ...]
) -> None:
    if not values:
        return
    if interface not in interfaces and len(interfaces) >= 32:
        worst = max(interfaces, key=lambda name: _rank(name, interfaces[name]))
        if _rank(interface, values) >= _rank(worst, interfaces[worst]):
            return
        del interfaces[worst]
    interfaces[interface] = values


def _selected(interfaces: dict[str, tuple[MetricValue, ...]]) -> tuple[MetricValue, ...]:
    names = sorted(interfaces, key=lambda name: _rank(name, interfaces[name]))
    return tuple(value for name in names for value in interfaces[name])


def parse_network(output: str) -> tuple[MetricValue, ...]:
    interfaces: dict[str, tuple[MetricValue, ...]] = {}
    for line in output.splitlines():
        interface, separator, raw = line.rpartition(":")
        if not separator:
            continue
        fields = raw.split()
        if len(fields) != 16:
            continue
        interface = interface.strip()
        values = _counters(interface, fields[0], fields[8])
        _retain(interfaces, interface, values)
    return _selected(interfaces)


def parse_ip_link(output: str) -> tuple[MetricValue, ...]:
    interfaces: dict[str, tuple[MetricValue, ...]] = {}
    interface: str | None = None
    direction: str | None = None
    receive: str | None = None
    for line in output.splitlines():
        match = re.match(r"\s*[0-9]+:\s+([^\s:]+):", line)
        if match:
            interface = match[1].partition("@")[0]
            receive = None
            direction = None
        elif line.strip().startswith("RX:"):
            direction = "receive"
        elif line.strip().startswith("TX:"):
            direction = "transmit"
        elif direction and interface:
            fields = line.split()
            if fields:
                if direction == "receive":
                    receive = fields[0]
                elif receive is not None:
                    values = _counters(interface, receive, fields[0])
                    _retain(interfaces, interface, values)
            direction = None
    return _selected(interfaces)


class NetworkCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_shell(adb, device.serial, ("cat", "/proc/net/dev"), self._timeout)
        values = parse_network(output) if output is not None else ()
        if not values:
            output = await read_shell(adb, device.serial, ("ip", "-s", "link"), self._timeout)
            values = parse_ip_link(output) if output is not None else ()
        if values:
            device.capabilities.add(DeviceCapability.NETWORK_METRICS)
        return snapshot(device, values)
