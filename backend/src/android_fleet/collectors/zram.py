"""Compressed swap (ZRAM) sizes summed across configured zram block devices."""

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_script, snapshot, validate_timeout
from android_fleet.devices.models import Device
from android_fleet.metrics.models import MetricSnapshot, MetricValue

# Kernels before 4.2 lack mm_stat and expose the same counters as separate files.
ZRAM_SCRIPT = """for z in /sys/block/zram[0-9]*; do
 [ -r "$z/disksize" ] || continue
 read -r d < "$z/disksize" || continue
 o=; c=; u=
 if [ -r "$z/mm_stat" ]; then read -r o c u r < "$z/mm_stat"
 else read -r o < "$z/orig_data_size"; read -r c < "$z/compr_data_size"
  read -r u < "$z/mem_used_total"; fi
 printf '%s %s %s %s %s\\n' "${z##*/}" "$d" "$o" "$c" "$u"
done 2>/dev/null"""

_FIELDS = ("zram_disk_size", "zram_original_data", "zram_compressed_data", "zram_memory_used")


def parse_zram(output: str) -> tuple[MetricValue, ...]:
    totals: list[int | None] = [0, 0, 0, 0]
    devices = 0
    for line in output.splitlines()[:16]:
        fields = line.split()
        if not fields or not fields[0].startswith("zram"):
            continue
        numbers: list[int | None] = []
        for raw in fields[1:5]:
            numbers.append(
                int(raw) if raw.isascii() and raw.isdecimal() and len(raw) < 20 else None
            )
        numbers += [None] * (4 - len(numbers))
        if not numbers[0]:
            # A zero disksize is an unconfigured device, not an empty swap.
            continue
        devices += 1
        for index, number in enumerate(numbers):
            current = totals[index]
            totals[index] = None if current is None or number is None else current + number
    if not devices:
        return ()
    return tuple(
        MetricValue(name, float(total), "bytes")
        for name, total in zip(_FIELDS, totals, strict=True)
        if total is not None
    )


class ZramCollector:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = validate_timeout(timeout)

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            return snapshot(device)
        output = await read_script(adb, device, ZRAM_SCRIPT, self._timeout)
        return snapshot(device, parse_zram(output) if output is not None else ())
