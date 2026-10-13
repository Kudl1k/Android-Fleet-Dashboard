import asyncio
import struct
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.execution.models import CommandResult
from android_fleet.screen.bridge import (
    CONFIG_FLAG,
    MAX_PACKET_BYTES,
    ScrcpyBridge,
    VideoPacket,
    encode_input,
    read_packet,
)
from android_fleet.screen.models import ScreenConfig


async def test_packet_preserves_official_flags_and_pts() -> None:
    packet = VideoPacket(b"\x00\x00\x00\x01\x65", 123456, config=True, keyframe=True)
    reader = asyncio.StreamReader()
    reader.feed_data(packet.wire())
    assert await read_packet(reader) == packet


@pytest.mark.parametrize("size", [0, MAX_PACKET_BYTES + 1])
async def test_packet_rejects_unbounded_lengths(size: int) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">QI", CONFIG_FLAG, size))
    with pytest.raises(RuntimeError, match="length"):
        await read_packet(reader)


async def test_packet_rejects_truncation() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">QI", 2, 4) + b"xx")
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await read_packet(reader)


def test_official_touch_key_text_layouts() -> None:
    pointer: dict[str, Any] = {
        "type": "pointer",
        "action": "down",
        "x": 20,
        "y": 40,
        "width": 720,
        "height": 1280,
    }
    assert encode_input(pointer) == struct.pack(
        ">BBQiiHHHII", 2, 0, 0, 20, 40, 720, 1280, 65535, 0, 0
    )
    pointer["action"] = "up"
    assert struct.unpack(">H", encode_input(pointer)[22:24])[0] == 0
    assert encode_input({"type": "text", "text": "café"}) == b"\1\0\0\0\5caf\xc3\xa9"
    assert encode_input({"type": "key", "action": "up", "keycode": 67}) == struct.pack(
        ">BBIII", 0, 1, 67, 0, 0
    )
    assert encode_input({"type": "nav", "key": "home"}) == struct.pack(
        ">BBIII", 0, 0, 3, 0, 0
    ) + struct.pack(">BBIII", 0, 1, 3, 0, 0)


def test_input_bounds() -> None:
    with pytest.raises(ValueError):
        encode_input(
            {"type": "pointer", "action": "down", "x": 720, "y": 1, "width": 720, "height": 1280}
        )
    with pytest.raises(ValueError):
        encode_input({"type": "text", "text": "é" * 151})


class TunnelAdb(FakeAdbClient):
    def __init__(self, port: int) -> None:
        super().__init__()
        self.port = port
        self.removed: list[int] = []

    async def forward(self, serial: str, socket: str) -> int:
        self.calls.append((serial, ("forward", socket)))
        return self.port

    async def remove_forward(self, serial: str, port: int, *, socket: str | None = None) -> None:
        self.removed.append(port)

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        self.calls.append((serial, argv))
        return CommandResult(exit_code=0)


async def test_start_stream_input_and_scoped_cleanup(tmp_path: Path) -> None:
    # Real TCP transport with official scrcpy framing, not a claim of hardware video.
    connections = 0
    received = asyncio.Future[bytes]()
    writers: list[asyncio.StreamWriter] = []

    async def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        writers.append(writer)
        if connections == 1:
            writer.write(b"\0" + struct.pack(">III", 0x68323634, 720, 1280))
            writer.write(VideoPacket(b"codec", 0, config=True).wire())
            await writer.drain()
        else:
            received.set_result(await reader.readexactly(28))

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    adb = TunnelAdb(server.sockets[0].getsockname()[1])
    bridge = ScrcpyBridge(adb, tmp_path / "server")
    stream = await bridge.start("fixture", ScreenConfig())
    try:
        assert (stream.width, stream.height, stream.codec) == (720, 1280, "h264")
        assert (await anext(stream.packets())).config
        await stream.send_input({"type": "nav", "key": "home"})
        assert len(await asyncio.wait_for(received, 1)) == 28
        script = next(
            argv[2] for _, argv in adb.calls if argv[:2] == ("sh", "-c") and "exec" in argv[2]
        )
        assert "power_on=false" in script
        assert "clipboard_autosync=false" in script
        assert "audio=false" in script
        await stream.close()
        await stream.close()
        assert adb.removed == [adb.port]
        assert any("kill" in argv[-1] for _, argv in adb.calls)
    finally:
        for writer in writers:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
        server.close()
        await server.wait_closed()


async def test_failed_start_removes_tunnel(tmp_path: Path) -> None:
    writers: list[asyncio.StreamWriter] = []

    async def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        writer.write(b"\0" + struct.pack(">III", 0x68323635, 720, 1280))
        await writer.drain()

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    adb = TunnelAdb(server.sockets[0].getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match="Unsupported"):
            await ScrcpyBridge(adb, tmp_path / "server").start("fixture", ScreenConfig())
        assert adb.removed == [adb.port]
    finally:
        for writer in writers:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
        server.close()
        await server.wait_closed()


async def test_fake_has_no_fabricated_video(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        await ScrcpyBridge(FakeAdbClient(), tmp_path / "server").start(
            "pixel-stock", ScreenConfig()
        )


async def test_recovery_cleans_only_owned_tunnels(tmp_path: Path) -> None:
    import json

    manifest = tmp_path / "transports.json"
    manifest.write_text(json.dumps({"01234567": {"serial": "fixture", "port": 54321}}))
    adb = TunnelAdb(54321)
    bridge = ScrcpyBridge(adb, tmp_path / "server", state_path=manifest)
    await bridge.recover()
    assert adb.removed == [54321]
    assert json.loads(manifest.read_text()) == {}
    cleanup = adb.calls[0][1][-1]
    assert "/data/local/tmp/fleet-scrcpy-01234567.jar.pid" in cleanup
    assert "pkill" not in cleanup


@pytest.mark.parametrize(
    "record",
    [
        {"../../unsafe": {"serial": "fixture", "port": 1}},
        {"01234567": {"serial": "-bad", "port": 1}},
        {"01234567": {"serial": "fixture", "port": 70000}},
        {"01234567": {"serial": "fixture", "port": 1, "path": "/unsafe"}},
    ],
)
async def test_recovery_rejects_tampered_manifest(tmp_path: Path, record: dict[str, Any]) -> None:
    import json

    manifest = tmp_path / "transports.json"
    manifest.write_text(json.dumps(record))
    adb = TunnelAdb(1)
    with pytest.raises(RuntimeError, match="Invalid"):
        await ScrcpyBridge(adb, tmp_path / "server", state_path=manifest).recover()
    assert not adb.calls
    assert not adb.removed
