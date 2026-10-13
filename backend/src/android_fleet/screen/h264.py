"""Bounded H.264 Annex B SPS geometry parsing; never decode picture content."""

import re


class _Bits:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def read(self, count: int = 1) -> int:
        if self.position + count > len(self.data) * 8:
            raise ValueError("Truncated SPS")
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.position // 8] >> (7 - self.position % 8)) & 1)
            self.position += 1
        return value

    def ue(self) -> int:
        zeros = 0
        while self.read() == 0:
            zeros += 1
            if zeros > 24:
                raise ValueError("Unbounded SPS integer")
        return (1 << zeros) - 1 + self.read(zeros)

    def se(self) -> int:
        value = self.ue()
        return (value + 1) // 2 if value % 2 else -(value // 2)


def _dimensions(nal: bytes) -> tuple[int, int]:
    # Remove emulation-prevention bytes from the sequence parameter set only.
    bits = _Bits(nal[1:].replace(b"\x00\x00\x03", b"\x00\x00"))
    profile = bits.read(8)
    bits.read(16)  # constraint flags and level
    bits.ue()  # SPS id
    chroma = 1
    separate_planes = False
    if profile in {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}:
        chroma = bits.ue()
        if chroma > 3:
            raise ValueError("Invalid chroma format")
        if chroma == 3:
            separate_planes = bool(bits.read())
        bits.ue()
        bits.ue()
        bits.read()
        if bits.read():
            for index in range(12 if chroma == 3 else 8):
                if bits.read():
                    last = next_scale = 8
                    for _ in range(16 if index < 6 else 64):
                        if next_scale:
                            next_scale = (last + bits.se() + 256) % 256
                        last = next_scale or last
    bits.ue()  # log2_max_frame_num_minus4
    order = bits.ue()
    if order == 0:
        bits.ue()
    elif order == 1:
        bits.read()
        bits.se()
        bits.se()
        cycle = bits.ue()
        if cycle > 255:
            raise ValueError("Unbounded SPS cycle")
        for _ in range(cycle):
            bits.se()
    elif order != 2:
        raise ValueError("Invalid picture order")
    bits.ue()
    bits.read()
    width = (bits.ue() + 1) * 16
    map_height = bits.ue() + 1
    frame_only = bits.read()
    if not frame_only:
        bits.read()
    bits.read()
    height = map_height * 16 * (2 - frame_only)
    if bits.read():
        left, right, top, bottom = (bits.ue() for _ in range(4))
        crop_chroma = 0 if separate_planes else chroma
        crop_x = 1 if crop_chroma in {0, 3} else 2
        crop_y = (2 if crop_chroma == 1 else 1) * (2 - frame_only)
        width -= crop_x * (left + right)
        height -= crop_y * (top + bottom)
    if not (0 < width <= 16384 and 0 < height <= 16384):
        raise ValueError("Invalid SPS dimensions")
    return width, height


def configuration_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return validated SPS geometry, or unknown for unsupported/malformed config."""
    if len(data) > 65536:
        return None
    for nal in re.split(b"\x00\x00(?:\x00)?\x01", data):
        if nal and nal[0] & 31 == 7:
            if nal[0] & 128:
                return None
            try:
                return _dimensions(nal)
            except ValueError:
                return None
    return None
