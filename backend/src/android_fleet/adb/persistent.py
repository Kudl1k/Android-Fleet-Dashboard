"""Persistent ADB over TCP on rooted (Magisk) devices, through a boot script.

Wireless Debugging picks a new port whenever it is enabled and stops after a reboot,
and `adb tcpip` also lasts only until the next reboot. A Magisk service.d script
re-enables ADB TCP on port 5555 at every boot, with a firewall that admits only the
monitoring server. The script mirrors device-setup/magisk/adb_tcp.sh.
"""

import ipaddress
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from android_fleet.adb.base import AdbClient
from android_fleet.devices.models import ConnectionType, DeviceCapability, DeviceState
from android_fleet.devices.service import DeviceUnavailable, FleetService

SCRIPT_VERSION = "v2"
SCRIPT_PATH = "/data/adb/service.d/adb_tcp.sh"
ADB_KEYS = "/data/misc/adb/adb_keys"
TCP_PORT = 5555
BOOT_SCRIPT = """#!/system/bin/sh
# android-fleet persistent-adb v2
# Magisk boot script: /data/adb/service.d/adb_tcp.sh (mode 0755, owner root).
#
# Re-enables authenticated ADB over TCP after every boot and restricts the ADB
# port to the central monitoring server. ADB RSA authentication stays enabled
# (ro.adb.secure is untouched); only keys in /data/misc/adb/adb_keys can connect.
# `adb_tcp.sh --firewall` applies only the firewall, without restarting adbd.

ADB_PORT=5555
# Only this address may reach the ADB port. The installer replaces the value.
SERVER_IP=__SERVER_IP__

firewall() {
  # A dedicated chain keeps the rules idempotent across reruns.
  iptables -N adb_guard 2>/dev/null
  iptables -F adb_guard
  iptables -A adb_guard -i lo -j RETURN
  iptables -A adb_guard -s "$SERVER_IP" -j RETURN
  iptables -A adb_guard -j DROP
  iptables -C INPUT -p tcp --dport "$ADB_PORT" -j adb_guard 2>/dev/null \\
    || iptables -I INPUT -p tcp --dport "$ADB_PORT" -j adb_guard
  # The server reaches phones over IPv4; ADB over IPv6 is closed entirely.
  ip6tables -C INPUT -p tcp --dport "$ADB_PORT" -j DROP 2>/dev/null \\
    || ip6tables -I INPUT -p tcp --dport "$ADB_PORT" -j DROP
}

if [ "$1" = "--firewall" ]; then
  firewall
  exit 0
fi

until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 5; done
# Wi-Fi is usually up a few seconds after boot_completed.
sleep 10
firewall
setprop service.adb.tcp.port "$ADB_PORT"
stop adbd
start adbd
log -t adb_tcp "ADB TCP $ADB_PORT enabled for $SERVER_IP"
"""
# Separates the key=value report from the raw socket tables in the inspection output.
SOCKETS_MARKER = "--sockets--"


def render_script(server_ip: str) -> str:
    return BOOT_SCRIPT.replace("__SERVER_IP__", str(ipaddress.IPv4Address(server_ip)))


def _proc_address(value: str) -> ipaddress.IPv4Address | None:
    """Decode a /proc/net/tcp{,6} address; IPv4-mapped IPv6 yields its IPv4 address."""
    host = value.partition(":")[0]
    try:
        raw = bytes.fromhex(host)
    except ValueError:
        return None
    # The kernel prints each 32-bit word in host (little-endian) byte order.
    words = b"".join(raw[i : i + 4][::-1] for i in range(0, len(raw), 4))
    if len(words) == 4:
        return ipaddress.IPv4Address(words)
    if len(words) == 16:
        return ipaddress.IPv6Address(words).ipv4_mapped
    return None


def server_addresses(tables: str, port: int) -> set[ipaddress.IPv4Address]:
    """Remote IPv4 peers of established TCP connections to the device's local ADB port."""
    peers: set[ipaddress.IPv4Address] = set()
    for line in tables.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[3] != "01" or ":" not in fields[1]:
            continue
        try:
            local_port = int(fields[1].rpartition(":")[2], 16)
        except ValueError:
            continue
        if local_port == port and (peer := _proc_address(fields[2])) is not None:
            peers.add(peer)
    return peers


@dataclass
class PersistenceStatus:
    state: str
    connection_type: str
    message: str
    installed: bool = False
    server_ip: str | None = None
    installed_server_ip: str | None = None
    tcp_port_active: bool = False
    key_authorized: bool | None = None


class PersistentTcp:
    def __init__(
        self,
        adb: AdbClient,
        fleet: FleetService,
        key_path: Path | None = None,
    ) -> None:
        self.adb = adb
        self.fleet = fleet
        self.key_path = key_path or Path.home() / ".android" / "adbkey.pub"

    def _server_key(self) -> str | None:
        """The local ADB server's public key; absent when ADB runs on another host."""
        try:
            key = self.key_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return key if key and "\n" not in key else None

    async def _root(self, serial: str, script: str, timeout: float = 10) -> str:
        result = await self.adb.shell(serial, ("su", "-c", script), timeout=timeout)
        if result.timeout:
            raise DeviceUnavailable("Device check timed out; keep the device online and retry")
        if result.exit_code != 0:
            raise DeviceUnavailable("Root command was denied; allow Shell root in Magisk")
        return result.stdout

    async def status(self, device_id: str) -> PersistenceStatus:
        config = self.fleet.configs.get(device_id) or await self.fleet.registry.get(device_id)
        device = self.fleet.get(device_id)
        kind = str(config.connection_type)
        if config.connection_type == ConnectionType.USB:
            return PersistenceStatus("not_applicable", kind, "USB devices do not use ADB TCP")
        if (
            device.state != DeviceState.ONLINE
            or DeviceCapability.ADB_SHELL not in device.capabilities
        ):
            return PersistenceStatus("offline", kind, "Connect the device to check ADB TCP")
        if not device.root_available:
            return PersistenceStatus(
                "root_required",
                kind,
                "Persistent ADB TCP needs root (Magisk). Without it, ADB TCP must be "
                "enabled again after every reboot.",
            )
        key = self._server_key()
        lines = [
            f"f={SCRIPT_PATH}",
            'if [ -f "$f" ]; then',
            "  echo version=$(sed -n 's/^# android-fleet persistent-adb //p' \"$f\")",
            "  echo server=$(sed -n 's/^SERVER_IP=//p' \"$f\")",
            "fi",
            "echo port=$(getprop service.adb.tcp.port)",
            "command -v magisk >/dev/null && echo magisk=1",
        ]
        if key:
            lines.append(f"grep -qxF {shlex.quote(key)} {ADB_KEYS} 2>/dev/null && echo key=1")
        lines += [f"echo {SOCKETS_MARKER}", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"]
        output = await self._root(device.serial, "\n".join(lines))
        report, _, tables = output.partition(SOCKETS_MARKER)
        values = {
            name: value
            for name, separator, value in (line.partition("=") for line in report.splitlines())
            if separator
        }
        peers = server_addresses(tables, config.port or TCP_PORT)
        server = str(next(iter(peers))) if len(peers) == 1 else None
        installed = "version" in values
        status = PersistenceStatus(
            state="persistent",
            connection_type=kind,
            message="ADB TCP on port 5555 is re-enabled after every reboot",
            installed=installed,
            server_ip=server,
            installed_server_ip=values.get("server") or None,
            tcp_port_active=values.get("port") == str(TCP_PORT),
            key_authorized=(values.get("key") == "1") if key else None,
        )
        if values.get("magisk") != "1":
            status.state, status.message = (
                "magisk_required",
                "Magisk was not found; persistent ADB TCP needs a Magisk boot script",
            )
        elif not installed:
            status.state, status.message = (
                "not_installed",
                "Persistent ADB TCP is not installed; the connection is lost after a reboot "
                "or when Wireless Debugging is turned off",
            )
        elif (
            values.get("version") != SCRIPT_VERSION
            or status.key_authorized is False
            or (server is not None and status.installed_server_ip != server)
        ):
            status.state, status.message = (
                "outdated",
                "Persistent ADB TCP is installed for a different server or version; reinstall it",
            )
        elif config.connection_type == ConnectionType.WIRELESS_ADB:
            status.state, status.message = (
                "switch_required",
                "Persistent ADB TCP is installed, but this device still uses the Wireless "
                "Debugging port; switch it to port 5555",
            )
        return status

    async def install(self, device_id: str) -> PersistenceStatus:
        """Install the boot script and firewall; the caller switches wireless devices."""
        status = await self.status(device_id)
        if status.state in {"offline", "root_required", "magisk_required", "not_applicable"}:
            raise DeviceUnavailable(status.message)
        server = status.server_ip
        if (
            server is None
            or not ipaddress.IPv4Address(server).is_private
            or (ipaddress.IPv4Address(server).is_loopback)
        ):
            raise DeviceUnavailable(
                "Cannot determine this server's LAN address from the device; connect it over "
                "the local network (not a USB forward) and retry"
            )
        device = self.fleet.get(device_id)
        steps = [
            "set -e",
            "mkdir -p /data/adb/service.d",
            f"printf '%s' {shlex.quote(render_script(server))} > {SCRIPT_PATH}.tmp",
            f"chown 0:0 {SCRIPT_PATH}.tmp",
            f"chmod 0755 {SCRIPT_PATH}.tmp",
            f"mv -f {SCRIPT_PATH}.tmp {SCRIPT_PATH}",
            # ADB shell (uid 2000) may use su silently: no toast on every metric poll.
            "magisk --sqlite 'REPLACE INTO policies (uid,policy,until,logging,notification) "
            "VALUES(2000,2,0,0,0)'",
        ]
        if key := self._server_key():
            quoted = shlex.quote(key)
            steps += [
                f"touch {ADB_KEYS}",
                f"grep -qxF {quoted} {ADB_KEYS} || echo {quoted} >> {ADB_KEYS}",
                f"chown system:shell {ADB_KEYS}",
                f"chmod 0640 {ADB_KEYS}",
            ]
        steps += [f"sh {SCRIPT_PATH} --firewall", "echo installed"]
        output = await self._root(device.serial, "\n".join(steps), timeout=20)
        if output.strip().splitlines()[-1:] != ["installed"]:
            raise DeviceUnavailable("Installation could not be verified on the device")
        return await self.status(device_id)


def status_payload(status: PersistenceStatus) -> dict[str, Any]:
    return asdict(status)
