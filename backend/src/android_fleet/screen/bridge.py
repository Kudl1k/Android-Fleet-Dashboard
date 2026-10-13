"""Pinned scrcpy 3.3.4 protocol bridge; no capture APK is installed.

Wire layouts follow Genymobile/scrcpy v3.3.4 Streamer.java and control_msg.c.
All device commands and process ownership remain behind AdbClient.
"""

import asyncio
import json
import os
import re
import secrets
import shlex
import struct
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from android_fleet.adb.base import AdbClient, AdbProcess
from android_fleet.screen.h264 import configuration_dimensions
from android_fleet.screen.models import ScreenConfig

MAX_PACKET_BYTES = 8 * 1024 * 1024
CONFIG_FLAG = 1 << 63
KEYFRAME_FLAG = 1 << 62
PTS_MASK = KEYFRAME_FLAG - 1


@dataclass(frozen=True)
class VideoPacket:
    data: bytes
    timestamp_us: int
    config: bool = False
    keyframe: bool = False

    def wire(self) -> bytes:
        flags = self.timestamp_us | (CONFIG_FLAG if self.config else 0)
        flags |= KEYFRAME_FLAG if self.keyframe else 0
        return struct.pack(">QI", flags, len(self.data)) + self.data


async def read_packet(reader: asyncio.StreamReader) -> VideoPacket:
    flags, size = struct.unpack(">QI", await reader.readexactly(12))
    if not 0 < size <= MAX_PACKET_BYTES:
        raise RuntimeError("Invalid scrcpy video packet length")
    return VideoPacket(
        await reader.readexactly(size),
        flags & PTS_MASK,
        bool(flags & CONFIG_FLAG),
        bool(flags & KEYFRAME_FLAG),
    )


def encode_input(event: dict[str, Any]) -> bytes:
    """Serialize the deliberately bounded subset of official scrcpy controls."""
    kind = event["type"]
    if kind == "pointer":
        action = {"down": 0, "up": 1, "move": 2, "cancel": 3}[event["action"]]
        x, y, width, height = (int(event[key]) for key in ("x", "y", "width", "height"))
        if not (0 < width <= 65535 and 0 < height <= 65535 and 0 <= x < width and 0 <= y < height):
            raise ValueError("Pointer outside video surface")
        # A touch pointer (not mouse) makes single-pointer mobile and desktop
        # gestures identical. Android transforms encoded frame coordinates.
        pressure = 0 if action in (1, 3) else 65535
        return struct.pack(">BBQiiHHHII", 2, action, 0, x, y, width, height, pressure, 0, 0)
    if kind == "key":
        action = {"down": 0, "up": 1}[event["action"]]
        return struct.pack(
            ">BBIII", 0, action, event["keycode"], event.get("repeat", 0), event.get("meta", 0)
        )
    if kind == "text":
        data = str(event["text"]).encode("utf-8")
        if not 0 < len(data) <= 300:
            raise ValueError("Text exceeds scrcpy text event limit")
        return struct.pack(">BI", 1, len(data)) + data
    if kind == "nav":
        key = {
            "back": 4,
            "home": 3,
            "recent": 187,
            "wake": 224,
            "volume_up": 24,
            "volume_down": 25,
        }[event["key"]]
        return struct.pack(">BBIII", 0, 0, key, 0, 0) + struct.pack(">BBIII", 0, 1, key, 0, 0)
    raise ValueError("Unsupported screen input")


class ScrcpyStream:
    def __init__(self, adb: AdbClient, serial: str, remote: str, pidfile: str) -> None:
        self.adb = adb
        self.serial = serial
        self.remote = remote
        self.pidfile = pidfile
        self.port: int | None = None
        self.process: AdbProcess | None = None
        self.reader: asyncio.StreamReader | None = None
        self.video_writer: asyncio.StreamWriter | None = None
        self.control_writer: asyncio.StreamWriter | None = None
        self.control_drain: asyncio.Task[None] | None = None
        self.width = 0
        self.height = 0
        self.codec = "h264"
        self.on_cleaned: Callable[[], Awaitable[None]] | None = None
        self.on_cleanup_failed: Callable[[], Awaitable[None]] | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._control_lock = asyncio.Lock()

    async def packets(self) -> AsyncIterator[VideoPacket]:
        assert self.reader is not None
        while not self._closed:
            packet = await read_packet(self.reader)
            if packet.config:
                dimensions = configuration_dimensions(packet.data)
                # Unknown geometry must fail closed for pointer input after reconfiguration.
                self.width, self.height = dimensions or (0, 0)
            yield packet

    async def send_input(self, event: dict[str, Any]) -> None:
        if self._closed or self.control_writer is None:
            raise RuntimeError("Control channel unavailable")
        payload = encode_input(event)
        async with self._control_lock:
            self.control_writer.write(payload)
            async with asyncio.timeout(2):
                await self.control_writer.drain()

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._cleanup())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            # Cancellation must not strand the process or tunnel halfway through cleanup.
            try:
                await self._close_task
            except Exception:
                pass
            raise

    async def _cleanup(self) -> None:
        self._closed = True
        errors: list[Exception] = []
        for writer in (self.control_writer, self.video_writer):
            if writer is not None:
                writer.close()
                try:
                    async with asyncio.timeout(2):
                        await writer.wait_closed()
                except (ConnectionError, BrokenPipeError):
                    # A reset is normal when the Android peer exits after socket closure.
                    pass
                except Exception as exc:
                    errors.append(exc)
        if self.control_drain:
            self.control_drain.cancel()
            await asyncio.gather(self.control_drain, return_exceptions=True)
        # Scoped PID file: never kill another scrcpy instance on this device.
        cleanup = (
            f"p=$(cat {shlex.quote(self.pidfile)} 2>/dev/null); "
            'case "$p" in ""|*[!0-9]*) ;; *) '
            "cmd=$(tr '\\000' ' ' < /proc/\"$p\"/cmdline 2>/dev/null); "
            'case "$cmd" in *com.genymobile.scrcpy.Server*'
            f"' scid={Path(self.remote).stem.removeprefix('fleet-scrcpy-')} '*) "
            'kill "$p" 2>/dev/null ;; esac ;; esac; '
            f"rm -f {shlex.quote(self.pidfile)} {shlex.quote(self.remote)}"
        )
        for attempt in range(2):
            try:
                result = await self.adb.shell(self.serial, ("sh", "-c", cleanup), timeout=5)
                if result.timeout or result.exit_code != 0:
                    raise RuntimeError("scrcpy device cleanup failed")
                break
            except Exception as exc:
                if attempt:
                    errors.append(exc)
                else:
                    await asyncio.sleep(0.1)
        if self.process:
            try:
                await self.process.close()
            except Exception as exc:
                errors.append(exc)
        if self.port is not None:
            try:
                await self.adb.remove_forward(
                    self.serial,
                    self.port,
                    socket="scrcpy_" + Path(self.remote).stem.removeprefix("fleet-scrcpy-"),
                )
            except Exception as exc:
                errors.append(exc)
        self.reader = None
        self.video_writer = None
        self.control_writer = None
        self.control_drain = None
        self.process = None
        if errors:
            if self.on_cleanup_failed:
                await self.on_cleanup_failed()
            raise RuntimeError("scrcpy cleanup incomplete") from errors[0]
        if self.on_cleaned is not None:
            await self.on_cleaned()


class ScrcpyBridge:
    def __init__(
        self,
        adb: AdbClient,
        server_path: Path,
        version: str = "3.3.4",
        state_path: Path | None = None,
    ) -> None:
        if version != "3.3.4":
            raise ValueError("Bridge requires scrcpy server 3.3.4")
        self.adb = adb
        self.server_path = server_path
        self.version = version
        self.state_path = state_path
        self._owned: dict[str, dict[str, Any]] = {}
        self._manifest_lock = asyncio.Lock()
        self._recovery_pending: set[str] = set()

    async def _save(self) -> None:
        if self.state_path is None:
            return
        payload = json.dumps(self._owned)
        path = self.state_path

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            if path.is_symlink() or temporary.is_symlink():
                raise RuntimeError("Unsafe screen transport manifest")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(payload)
            temporary.chmod(0o600)
            temporary.replace(path)

        await asyncio.to_thread(write)

    async def recover(self) -> int:
        """Clean only owned, validated transports after an unclean backend exit."""
        if self.state_path is None or not await asyncio.to_thread(self.state_path.exists):
            return 0
        if self.state_path.is_symlink() or self.state_path.stat().st_size > 65536:
            raise RuntimeError("Unsafe screen transport manifest")
        raw = await asyncio.to_thread(self.state_path.read_text)
        records = json.loads(raw)
        if not isinstance(records, dict):
            raise RuntimeError("Invalid screen transport manifest")
        async with self._manifest_lock:
            failures = 0
            for scid, record in records.items():
                if not isinstance(scid, str) or not re.fullmatch(r"[0-7][0-9a-f]{7}", scid):
                    raise RuntimeError("Invalid owned screen transport")
                if not isinstance(record, dict) or set(record) != {"serial", "port"}:
                    raise RuntimeError("Invalid owned screen transport")
                serial, port = record["serial"], record["port"]
                if not isinstance(serial, str) or not serial or serial.startswith("-"):
                    raise RuntimeError("Invalid owned screen device")
                if port is not None and (type(port) is not int or not 1 <= port <= 65535):
                    raise RuntimeError("Invalid owned screen port")
                self._owned[scid] = record
                remote = f"/data/local/tmp/fleet-scrcpy-{scid}.jar"
                stale = ScrcpyStream(self.adb, serial, remote, remote + ".pid")
                stale.port = port
                try:
                    await stale.close()
                except Exception:
                    failures += 1
                    self._recovery_pending.add(scid)
                else:
                    del self._owned[scid]
            await self._save()
            return failures

    async def retry_recovery(self) -> int:
        """Retry stale offline transports without touching current live streams."""
        failures = 0
        async with self._manifest_lock:
            for scid in tuple(self._recovery_pending):
                record = self._owned[scid]
                remote = f"/data/local/tmp/fleet-scrcpy-{scid}.jar"
                stale = ScrcpyStream(self.adb, record["serial"], remote, remote + ".pid")
                stale.port = record["port"]
                try:
                    await stale.close()
                except Exception:
                    failures += 1
                else:
                    del self._owned[scid]
                    self._recovery_pending.remove(scid)
            if self._recovery_pending or failures == 0:
                await self._save()
        return failures

    async def _record(self, scid: str, serial: str, port: int | None) -> None:
        async with self._manifest_lock:
            self._owned[scid] = {"serial": serial, "port": port}
            await self._save()

    async def _forget(self, scid: str) -> None:
        async with self._manifest_lock:
            self._owned.pop(scid, None)
            await self._save()

    async def _mark_failed(self, scid: str) -> None:
        async with self._manifest_lock:
            self._recovery_pending.add(scid)

    async def start(self, serial: str, config: ScreenConfig) -> ScrcpyStream:
        if config.codec != "h264":
            raise ValueError("Only H.264 is supported")
        scid = f"{secrets.randbelow(1 << 31):08x}"
        remote = f"/data/local/tmp/fleet-scrcpy-{scid}.jar"
        stream = ScrcpyStream(self.adb, serial, remote, remote + ".pid")
        stream.on_cleaned = lambda: self._forget(scid)
        stream.on_cleanup_failed = lambda: self._mark_failed(scid)
        try:
            await self._record(scid, serial, None)
            async with asyncio.timeout(20):
                await self.adb.push(serial, self.server_path, remote)
                stream.port = await self.adb.forward(serial, f"scrcpy_{scid}")
                await self._record(scid, serial, stream.port)
                args = (
                    "env",
                    f"CLASSPATH={remote}",
                    "app_process",
                    "/",
                    "com.genymobile.scrcpy.Server",
                    self.version,
                    f"scid={scid}",
                    "tunnel_forward=true",
                    "audio=false",
                    "control=true",
                    "send_device_meta=false",
                    "clipboard_autosync=false",
                    "power_on=false",
                    "cleanup=false",
                    "log_level=warn",
                    "video_codec=h264",
                    "video_codec_options=i-frame-interval=1",
                    f"max_size={config.max_size}",
                    f"max_fps={config.max_fps}",
                    f"video_bit_rate={config.bitrate}",
                )
                script = f"echo $$ > {shlex.quote(stream.pidfile)}; exec {shlex.join(args)}"
                stream.process = await self.adb.start_shell(serial, ("sh", "-c", script))
                # ADB forward accepts before the Android socket is ready; the
                # dummy byte is the official server-readiness handshake.
                while True:
                    reader, writer = await asyncio.open_connection("127.0.0.1", stream.port)
                    try:
                        async with asyncio.timeout(1):
                            dummy = await reader.readexactly(1)
                        if dummy != b"\0":
                            raise RuntimeError("Invalid scrcpy handshake")
                        stream.reader, stream.video_writer = reader, writer
                        break
                    except (TimeoutError, asyncio.IncompleteReadError, ConnectionError):
                        writer.close()
                        await writer.wait_closed()
                        await asyncio.sleep(0.1)
                control_reader, stream.control_writer = await asyncio.open_connection(
                    "127.0.0.1", stream.port
                )
                stream.control_drain = asyncio.create_task(_discard_control(control_reader))
                codec_id, stream.width, stream.height = struct.unpack(
                    ">III", await reader.readexactly(12)
                )
                if codec_id != 0x68323634 or not (
                    0 < stream.width <= 16384 and 0 < stream.height <= 16384
                ):
                    raise RuntimeError("Unsupported scrcpy codec or dimensions")
                return stream
        except BaseException:
            try:
                await stream.close()
            except Exception:
                pass
            raise


async def _discard_control(reader: asyncio.StreamReader) -> None:
    # Clipboard autosync is disabled; do not retain device channel contents.
    while await reader.read(4096):
        pass
