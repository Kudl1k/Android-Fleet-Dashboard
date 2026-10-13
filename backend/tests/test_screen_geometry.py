"""Synthetic SPS fixtures model portrait, landscape, crop and malformed config."""

import asyncio
from collections.abc import Iterable

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.screen.bridge import ScrcpyStream, VideoPacket
from android_fleet.screen.h264 import configuration_dimensions


def sps(
    width: int,
    height: int,
    *,
    high: bool = False,
    chroma: int = 1,
    separate_planes: bool = False,
    scaling: bool = False,
) -> bytes:
    parts: list[str] = []

    def raw(value: int, size: int = 1) -> None:
        parts.append(f"{value:0{size}b}")

    def ue(value: int) -> None:
        coded = f"{value + 1:b}"
        parts.append("0" * (len(coded) - 1) + coded)

    raw(100 if high else 66, 8)
    raw(0, 8)
    raw(31, 8)
    ue(0)
    if high:
        ue(chroma)
        if chroma == 3:
            raw(int(separate_planes))
        ue(0)
        ue(0)
        raw(0)
        raw(int(scaling))
        if scaling:
            for index in range(12 if chroma == 3 else 8):
                raw(1)
                for _ in range(16 if index < 6 else 64):
                    ue(0)  # signed delta_scale 0
    ue(0)
    ue(0)
    ue(0)
    ue(1)
    raw(0)
    ue((width + 15) // 16 - 1)
    ue((height + 15) // 16 - 1)
    raw(1)
    raw(1)
    raw(1)
    ue(0)
    crop_x = 1 if separate_planes or chroma in {0, 3} else 2
    crop_y = 2 if chroma == 1 and not separate_planes else 1
    ue(((width + 15) // 16 * 16 - width) // crop_x)
    ue(0)
    ue(((height + 15) // 16 * 16 - height) // crop_y)
    raw(0)
    raw(1)
    binary = "".join(parts)
    binary += "0" * (-len(binary) % 8)
    rbsp = int(binary, 2).to_bytes(len(binary) // 8, "big")
    escaped = bytearray()
    zeros = 0
    for byte in rbsp:
        if zeros >= 2 and byte <= 3:
            escaped.append(3)
            zeros = 0
        escaped.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return b"\x00\x00\x00\x01\x67" + escaped


@pytest.mark.parametrize("dims", [(592, 1280), (1280, 592), (336, 720), (480, 1040)])
@pytest.mark.parametrize("high", [False, True])
def test_sps_geometry(dims: tuple[int, int], high: bool) -> None:
    assert configuration_dimensions(sps(*dims, high=high)) == dims


@pytest.mark.parametrize(
    "data", [b"", b"codec", b"\0\0\1\x67", b"\0\0\1\x67" + b"\0" * 100, b"x" * 65537]
)
def test_malformed_geometry_fails_closed(data: bytes) -> None:
    assert configuration_dimensions(data) is None


async def test_stream_observes_rotation_and_unknown_configuration() -> None:
    stream = ScrcpyStream(FakeAdbClient(), "fixture", "/tmp/fixture", "/tmp/fixture.pid")
    stream.reader = asyncio.StreamReader()
    configs: Iterable[tuple[int, int]] = [(592, 1280), (1280, 592), (336, 720)]
    for dimensions in configs:
        stream.reader.feed_data(VideoPacket(sps(*dimensions), 0, config=True).wire())
        assert (await anext(stream.packets())).config
        assert (stream.width, stream.height) == dimensions
    stream.reader.feed_data(VideoPacket(b"invalid", 0, config=True).wire())
    await anext(stream.packets())
    assert (stream.width, stream.height) == (0, 0)


@pytest.mark.parametrize(
    "chroma,separate", [(0, False), (1, False), (2, False), (3, False), (3, True)]
)
def test_high_profile_scaling_lists_and_crop_units(chroma: int, separate: bool) -> None:
    assert configuration_dimensions(
        sps(590, 1278, high=True, chroma=chroma, separate_planes=separate, scaling=True)
    ) == (590, 1278)


def test_separate_planes_preserve_twelve_scaling_lists() -> None:
    # Odd crop requires monochrome units while scaling lists still follow chroma_format_idc=3.
    assert configuration_dimensions(
        sps(591, 1279, high=True, chroma=3, separate_planes=True, scaling=True)
    ) == (591, 1279)


def test_invalid_nal_header_and_truncated_scaling_list_fail_closed() -> None:
    config = sps(592, 1280, high=True, scaling=True)
    assert configuration_dimensions(config[:4] + b"\xe7" + config[5:]) is None
    assert configuration_dimensions(config[:15]) is None
