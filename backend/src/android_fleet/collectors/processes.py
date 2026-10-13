"""Process count and bounded top-N CPU/memory consumers from /proc/<pid>/stat.

CPU usage is a delta of utime+stime between two polls (first poll is a baseline)
expressed in cores, so 1.0 means one fully busy core. Only the top consumers become
``process`` labels, keyed by name rather than PID to keep series cardinality bounded.
"""

import re
import time
from collections.abc import Callable

from android_fleet.adb.base import AdbClient
from android_fleet.collectors.common import can_collect, read_script, snapshot, validate_timeout
from android_fleet.devices.models import Device, DeviceCapability
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricSnapshot, MetricValue

# cmdline is read through the shell builtin, which stops at the first NUL (argv[0]).
PROCESS_SCRIPT = """for p in /proc/[0-9]*; do
 s=; read -r s < "$p/stat" || continue
 c=; read -r c < "$p/cmdline"
 printf '%s\\t%s\\n' "$s" "$c"
done 2>/dev/null"""
USER_HZ = 100  # Linux always reports /proc tick counters in USER_HZ units to userspace.
PAGE_SIZE = 4096
TOP = 5


def _name(comm: str, cmdline: str) -> str:
    command = cmdline.strip().split(" ")[0].rsplit("/", 1)[-1] if cmdline.strip() else ""
    # Kernel truncates comm to 15 bytes; prefer the full argv[0] when it is consistent.
    # Zygote and its unspecialized children keep the generic comm "main" (seen on Pixel 3a).
    name = command if command and (comm[:15] in command or comm == "main") else comm
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", name.strip())[:64] or "unknown"


def parse_processes(output: str) -> dict[int, tuple[str, int, int, int]]:
    """Return pid -> (name, cpu ticks, start time, rss bytes)."""
    processes: dict[int, tuple[str, int, int, int]] = {}
    for line in output.splitlines()[:65536]:
        stat, _, cmdline = line.partition("\t")
        head, separator, tail = stat.rpartition(")")
        pid_text, _, comm = head.partition(" (")
        if not separator or not pid_text.isascii() or not pid_text.isdecimal():
            continue
        fields = tail.split()
        # Fields after comm start at state (3): utime=14, stime=15, starttime=22, rss=24.
        if len(fields) < 22:
            continue
        try:
            utime, stime = int(fields[11]), int(fields[12])
            start, rss = int(fields[19]), int(fields[21])
        except ValueError:
            continue
        if min(utime, stime, start, rss) < 0:
            continue
        processes[int(pid_text)] = (_name(comm, cmdline), utime + stime, start, rss * PAGE_SIZE)
    return processes


def process_metrics(
    previous: dict[int, tuple[str, int, int, int]] | None,
    current: dict[int, tuple[str, int, int, int]],
    elapsed: float | None,
) -> tuple[MetricValue, ...]:
    if not current:
        return ()
    values = [MetricValue("process_count", float(len(current)), "count")]
    memory: dict[str, int] = {}
    for name, _, _, rss in current.values():
        memory[name] = memory.get(name, 0) + rss
    for name, rss in sorted(memory.items(), key=lambda item: (-item[1], item[0]))[:TOP]:
        values.append(MetricValue("process_memory", float(rss), "bytes", (("process", name),)))
    if previous is not None and elapsed is not None and elapsed > 0:
        cpu: dict[str, float] = {}
        for pid, (name, ticks, start, _) in current.items():
            old = previous.get(pid)
            # A different start time means the PID was reused by a new process.
            if old is None or old[2] != start or ticks < old[1]:
                continue
            cpu[name] = cpu.get(name, 0.0) + (ticks - old[1]) / USER_HZ / elapsed
        busiest = sorted(cpu.items(), key=lambda item: (-item[1], item[0]))[:TOP]
        for name, usage in busiest:
            if usage > 0:
                values.append(MetricValue("process_cpu", usage, "ratio", (("process", name),)))
    return tuple(value for value in values if valid_metric(value))


class ProcessCollector:
    def __init__(
        self, *, timeout: float = 5.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._timeout = validate_timeout(timeout)
        self._clock = clock
        self._previous: dict[int, tuple[str, int, int, int]] | None = None
        self._previous_at: float | None = None

    async def collect(self, device: Device, adb: AdbClient) -> MetricSnapshot:
        if not can_collect(device):
            self._previous = self._previous_at = None
            return snapshot(device)
        output = await read_script(adb, device, PROCESS_SCRIPT, self._timeout)
        now = self._clock()
        current = parse_processes(output) if output is not None else {}
        elapsed = now - self._previous_at if self._previous_at is not None else None
        values = process_metrics(self._previous, current, elapsed)
        self._previous, self._previous_at = (current, now) if current else (None, None)
        if values:
            device.capabilities.add(DeviceCapability.PROCESS_LIST)
        return snapshot(device, values)
