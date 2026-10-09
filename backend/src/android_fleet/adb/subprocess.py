"""The only production subprocess boundary for Android communication."""

import asyncio
import ipaddress
import os
import re
import shlex
import time
from contextlib import suppress

from android_fleet.devices.models import DeviceState
from android_fleet.discovery.models import MdnsService
from android_fleet.execution.models import CommandResult


class SubprocessAdbClient:
    def __init__(
        self,
        executable: str = "adb",
        server_host: str | None = None,
        server_port: int = 5037,
        timeout: float = 10.0,
    ) -> None:
        self._prefix = [executable]
        if server_host:
            self._prefix.extend(["-H", server_host])
        self._prefix.extend(["-P", str(server_port)])
        self._timeout = timeout

    async def _run(self, args: list[str], timeout: float) -> CommandResult:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        started = time.monotonic()
        environment = os.environ.copy()
        # Registry intent owns connection policy for servers started by this adapter.
        environment["ADB_MDNS_AUTO_CONNECT"] = "0"
        process = await asyncio.create_subprocess_exec(
            *self._prefix,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )

        async def bounded_read(stream: asyncio.StreamReader | None) -> bytes:
            assert stream is not None
            output = bytearray()
            while chunk := await stream.read(65536):
                output.extend(chunk)
                if len(output) > 1024 * 1024:
                    raise RuntimeError("ADB output limit exceeded")
            return bytes(output)

        readers = [
            asyncio.create_task(bounded_read(process.stdout)),
            asyncio.create_task(bounded_read(process.stderr)),
        ]

        async def communicate() -> tuple[bytes, bytes]:
            stdout, stderr = await asyncio.gather(*readers)
            await process.wait()
            return stdout, stderr

        communication = asyncio.create_task(communicate())

        async def terminate() -> None:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            communication.cancel()
            for reader in readers:
                reader.cancel()
            await asyncio.gather(communication, *readers, return_exceptions=True)

            async def discard(stream: asyncio.StreamReader | None) -> None:
                assert stream is not None
                while await stream.read(65536):
                    pass

            await asyncio.gather(discard(process.stdout), discard(process.stderr))
            await process.wait()

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout)
        except TimeoutError:
            timed_out = True
            await terminate()
            stdout, stderr = b"", b""
        except asyncio.CancelledError:
            await terminate()
            raise
        except Exception:
            await terminate()
            raise
        return CommandResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=process.returncode,
            duration=time.monotonic() - started,
            timeout=timed_out,
        )

    async def list_devices(self) -> dict[str, DeviceState]:
        result = await self._run(["devices", "-l"], self._timeout)
        if result.timeout or result.exit_code != 0:
            raise RuntimeError("ADB device enumeration failed")
        states = {
            "device": DeviceState.ONLINE,
            "offline": DeviceState.OFFLINE,
            "unauthorized": DeviceState.UNAUTHORIZED,
        }
        devices: dict[str, DeviceState] = {}
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and not line.startswith(("List of devices", "*")):
                devices[fields[0]] = states.get(fields[1], DeviceState.ERROR)
        return devices

    async def shell(
        self,
        serial: str,
        argv: tuple[str, ...],
        *,
        timeout: float = 10.0,
    ) -> CommandResult:
        if not serial or not argv:
            raise ValueError("serial and command are required")
        return await self._run(["-s", serial, "shell", shlex.join(argv)], timeout)

    async def command(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 30.0
    ) -> CommandResult:
        if not serial or serial.startswith("-") or not argv:
            raise ValueError("Invalid ADB command")
        allowed = argv == ("reboot",) or (
            len(argv) == 2 and argv[0] in {"install", "uninstall"} and not argv[1].startswith("-")
        )
        if not allowed:
            raise ValueError("ADB command is not allowlisted")
        return await self._run(["-s", serial, *argv], timeout)

    async def screenshot(
        self, serial: str, *, timeout: float = 30.0, max_bytes: int = 16777216
    ) -> bytes:
        if not serial or serial.startswith("-") or timeout <= 0 or max_bytes <= 0:
            raise ValueError("Invalid screenshot arguments")
        process = await asyncio.create_subprocess_exec(
            *self._prefix,
            "-s",
            serial,
            "exec-out",
            "screencap",
            "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(timeout):
                assert process.stdout is not None
                output = bytearray()
                while chunk := await process.stdout.read(65536):
                    output.extend(chunk)
                    if len(output) > max_bytes:
                        raise RuntimeError("Screenshot size limit exceeded")
                await process.wait()
                if process.returncode != 0 or not output.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise RuntimeError("Screenshot unsupported or unavailable")
                return bytes(output)
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                assert process.stdout is not None
                while await process.stdout.read(65536):
                    pass
                await process.wait()

    async def connect(self, address: str) -> CommandResult:
        if not address or address.startswith("-"):
            raise ValueError("connection address is required and must not be an option")
        return await self._run(["connect", address], self._timeout)

    async def disconnect(self, address: str) -> CommandResult:
        if not address or address.startswith("-"):
            raise ValueError("connection address is required and must not be an option")
        return await self._run(["disconnect", address], self._timeout)

    async def mdns_services(self) -> tuple[MdnsService, ...]:
        result = await self._run(["mdns", "services"], self._timeout)
        if result.timeout or result.exit_code != 0:
            raise RuntimeError("ADB mDNS enumeration failed")
        return parse_mdns(result.stdout)


def _mdns_host(value: str) -> str | None:
    bracketed = value.startswith("[") and value.endswith("]")
    if "[" in value or "]" in value:
        if not bracketed:
            return None
        value = value[1:-1]
    if not value or "%" in value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if bracketed:
            return None
        hostname = value.lower().removesuffix(".")
        labels = hostname.split(".")
        if len(hostname) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
        ):
            return None
        return hostname
    if bracketed and address.version != 6:
        return None
    return str(address)


def parse_mdns(output: str) -> tuple[MdnsService, ...]:
    """Parse ADB records without guessing device identities from network hosts."""
    services: list[MdnsService] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        name, service_type, endpoint = fields
        service_type = service_type.lower().rstrip(".")
        if service_type not in {"_adb-tls-connect._tcp", "_adb-tls-pairing._tcp", "_adb._tcp"}:
            continue
        host, separator, raw_port = endpoint.rpartition(":")
        if not separator:
            continue
        parsed_host = _mdns_host(host)
        if parsed_host is None or not raw_port.isascii() or not raw_port.isdecimal():
            continue
        host = parsed_host
        try:
            port = int(raw_port)
        except ValueError:
            continue
        if not host or not 1 <= port <= 65535:
            continue
        name = name.lower().removesuffix(".local.").removesuffix(".local").rstrip(".")
        if not name.endswith(f".{service_type}"):
            name = f"{name}.{service_type}"
        instance = name.removesuffix(f".{service_type}")
        if re.fullmatch(r"[a-z0-9_-]{1,128}", instance) is None:
            continue
        service = MdnsService(name=name, service_type=service_type, host=host, port=port)
        if service not in services:
            services.append(service)
    return tuple(services)
