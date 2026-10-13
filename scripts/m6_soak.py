"""Bounded, no-input streaming soak. Results contain counters, never video or credentials."""

import argparse
import asyncio
import json
import math
import os
import time
import urllib.parse
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

QUALITY = {
    "low": {"max_size": 480, "max_fps": 15, "bitrate": 1_000_000},
    "medium": {"max_size": 720, "max_fps": 30, "bitrate": 3_000_000},
    "high": {"max_size": 1080, "max_fps": 30, "bitrate": 6_000_000},
}


class Transport(Protocol):
    async def connect(self) -> None: ...
    async def receive(self) -> int: ...
    async def sample(self) -> dict[str, Any]: ...
    async def close(self) -> bool: ...


class SimulatedTransport:
    """Finite queue and timed encoded packets; this does not simulate a browser decoder."""

    def __init__(self, fps: int = 30, packet_size: int = 4096) -> None:
        self.fps = fps
        self.packet_size = packet_size
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=8)
        self.task: asyncio.Task[None] | None = None
        self.dropped = 0

    async def connect(self) -> None:
        async def produce() -> None:
            while True:
                await asyncio.sleep(1 / self.fps)
                if self.queue.full():
                    self.queue.get_nowait()
                    self.dropped += 1
                self.queue.put_nowait(self.packet_size)

        self.task = asyncio.create_task(produce())

    async def receive(self) -> int:
        return await self.queue.get()

    async def sample(self) -> dict[str, Any]:
        return {
            "synthetic": True,
            "queue_depth": self.queue.qsize(),
            "dropped": self.dropped,
        }

    async def close(self) -> bool:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        while not self.queue.empty():
            self.queue.get_nowait()
        return True


class LiveTransport:
    def __init__(self, base: str, token: str, device: str, quality: str, origin: str) -> None:
        parsed = urllib.parse.urlsplit(base)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Live backend must be a local HTTP URL")
        if not token or any(c.isspace() for c in token):
            raise ValueError("Authentication token required")
        self.base = base.rstrip("/")
        self.token = token
        self.device = urllib.parse.quote(device, safe="")
        self.quality = quality
        self.origin = origin
        self.sid: str | None = None
        self.socket: Any = None
        self.client: Any = None
        self.heartbeat: asyncio.Task[None] | None = None

    async def request(self, method: str, path: str, body: Any = None) -> Any:
        response = await self.client.request(method, path, json=body)
        response.raise_for_status()
        return response.json()

    async def connect(self) -> None:
        import httpx
        from websockets.asyncio.client import connect
        from websockets.typing import Origin

        self.client = httpx.AsyncClient(
            base_url=self.base,
            headers={"Authorization": "Bearer " + self.token},
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        )
        session = await self.request(
            "POST",
            f"/api/v1/devices/{self.device}/screen/sessions",
            QUALITY[self.quality],
        )
        self.sid = session["id"]
        ticket = await self.request("POST", f"/api/v1/screen/sessions/{self.sid}/ticket")
        self.socket = await connect(
            self.base.replace("http://", "ws://", 1) + f"/api/v1/screen/sessions/{self.sid}/stream",
            origin=Origin(self.origin),
            max_queue=8,
            max_size=16 * 1024 * 1024,
            proxy=None,
        )
        await self.socket.send(json.dumps({"ticket": ticket["ticket"]}))
        self.heartbeat = asyncio.create_task(self.keep_alive())

    async def keep_alive(self) -> None:
        while True:
            await self.socket.send('{"type":"ping"}')
            await asyncio.sleep(10)

    async def receive(self) -> int:
        message = await self.socket.recv()
        if isinstance(message, bytes):
            return len(message)
        metadata = json.loads(message)
        if metadata.get("type") == "status" and metadata.get("state") in {
            "failed",
            "stopped",
            "timed_out",
        }:
            raise RuntimeError("Stream terminated")
        return 0

    async def sample(self) -> dict[str, Any]:
        if self.heartbeat and self.heartbeat.done():
            self.heartbeat.result()
        readiness = await self.request("GET", "/ready")
        session = await self.request("GET", f"/api/v1/screen/sessions/{self.sid}")
        if readiness.get("status") != "ready" or session.get("state") not in {
            "starting",
            "streaming",
            "reconnecting",
        }:
            raise RuntimeError("Unhealthy stream or backend")
        stats = session.get("statistics", {})
        # Explicit allowlist prevents future API additions leaking private content.
        return {
            key: value
            for key, value in stats.items()
            if key
            in {
                "frames_received",
                "dropped_frames",
                "bytes_transferred",
                "startup_seconds",
            }
            and isinstance(value, (int, float))
        }

    async def close(self) -> bool:
        clean = True
        try:
            if self.heartbeat:
                self.heartbeat.cancel()
                await asyncio.gather(self.heartbeat, return_exceptions=True)
                self.heartbeat = None
            if self.socket:
                await self.socket.close()
            if self.sid and self.client:
                result = await self.request("DELETE", f"/api/v1/screen/sessions/{self.sid}")
                clean = result.get("state") in {"stopped", "failed", "timed_out"}
        except Exception:  # noqa: BLE001 - record failure without disclosing transport secrets
            clean = False
        finally:
            if self.client:
                await self.client.aclose()
            self.socket = self.client = None
            self.sid = None
        return clean


CONTAINER_SAMPLE = """
import asyncio,json
from pathlib import Path
from android_fleet.adb.subprocess import SubprocessAdbClient
from android_fleet.core.settings import Settings
async def sample():
    result = dict(rss_bytes=None,open_fds=None,container_memory_bytes=None,
                  adb_forward_count=None,owned_adb_forward_count=None,
                  transport_manifest_entries=None,orphan_process_count=None)
    try:
        for line in Path('/proc/1/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                result['rss_bytes'] = int(line.split()[1])*1024
        result['open_fds'] = len(list(Path('/proc/1/fd').iterdir()))
    except (OSError,ValueError): pass
    try:
        result['container_memory_bytes'] = int(Path('/sys/fs/cgroup/memory.current').read_text())
    except (OSError,ValueError): pass
    try:
        settings = Settings()
        records = None
        path = Path(settings.registry_path).parent/'screen-transports.json'
        if path.exists() and not path.is_symlink() and path.stat().st_size <= 65536:
            records = json.loads(path.read_text())
            if isinstance(records,dict): result['transport_manifest_entries'] = len(records)
        elif not path.exists():
            result['transport_manifest_entries'] = 0
            records = {}
        adb = SubprocessAdbClient(server_host=settings.adb_server_host,
                                  server_port=settings.adb_server_port,timeout=5)
        forwards = await adb.list_forwards()
        result['adb_forward_count'] = len(forwards)
        if isinstance(records,dict):
            sockets = {'localabstract:scrcpy_'+scid for scid in records if isinstance(scid,str)}
            result['owned_adb_forward_count'] = sum(remote in sockets for _,_,remote in forwards)
    except Exception: pass
    print(json.dumps(result))
asyncio.run(sample())
"""


async def command_output(argv: tuple[str, ...], timeout: float = 15) -> bytes:
    """Bounded stdout, suppressed stderr, and kill/reap on timeout or cancellation."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert process.stdout is not None
    try:
        async with asyncio.timeout(timeout):
            chunks = bytearray()
            while chunk := await process.stdout.read(8192):
                chunks.extend(chunk)
                if len(chunks) > 65536:
                    raise ValueError("Resource output exceeded limit")
            await process.wait()
            if process.returncode:
                raise RuntimeError("Resource command failed")
            return bytes(chunks)
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def container_resources(container: str) -> dict[str, Any]:
    # Restrict identifiers, even though all invocations use argv with no local shell.
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise ValueError("Invalid container identifier")
    result: dict[str, Any] = {
        key: None
        for key in (
            "rss_bytes",
            "cpu_percent",
            "open_fds",
            "container_memory_bytes",
            "adb_forward_count",
            "owned_adb_forward_count",
            "transport_manifest_entries",
            "orphan_process_count",
        )
    }
    observations = await asyncio.gather(
        command_output(("docker", "exec", container, "python", "-c", CONTAINER_SAMPLE)),
        command_output(("docker", "stats", "--no-stream", "--format", "{{json .}}", container)),
        return_exceptions=True,
    )
    for index, observation in enumerate(observations):
        if isinstance(observation, BaseException):
            continue
        try:
            parsed = json.loads(observation)
            if index == 0:
                for key in result:
                    value = parsed.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        result[key] = value
            else:
                result["cpu_percent"] = float(parsed["CPUPerc"].removesuffix("%"))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    return result


async def resources(pid: int | None) -> dict[str, Any]:
    """Sample an explicitly supplied backend PID; unavailable fields remain null."""
    result: dict[str, Any] = {"rss_bytes": None, "cpu_percent": None, "open_fds": None}
    if pid is None:
        return result
    try:
        process = await asyncio.create_subprocess_exec(
            "ps",
            "-p",
            str(pid),
            "-o",
            "rss=,pcpu=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), 5)
        fields = stdout.decode().split()
        if process.returncode == 0 and len(fields) == 2:
            result.update(rss_bytes=int(fields[0]) * 1024, cpu_percent=float(fields[1]))
    except (OSError, ValueError, TimeoutError):
        if "process" in locals() and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    try:
        result["open_fds"] = await asyncio.to_thread(
            lambda: len(list(Path(f"/proc/{pid}/fd").iterdir()))
        )
    except OSError:
        pass
    return result


async def run_soak(
    transports: list[Transport],
    duration: float,
    sample_seconds: float = 10,
    reconnect_seconds: float = 0,
    backend_pid: int | None = None,
    container: str | None = None,
) -> dict[str, Any]:
    if not transports or any(not math.isfinite(v) or v <= 0 for v in (duration, sample_seconds)):
        raise ValueError("Positive finite duration, sampling interval and viewers required")
    if not math.isfinite(reconnect_seconds) or reconnect_seconds < 0:
        raise ValueError("Invalid reconnect interval")
    if duration / sample_seconds > 10000:
        raise ValueError("At most 10000 resource samples; increase sampling interval")
    baseline_resources = await container_resources(container) if container else None
    started = time.monotonic()
    locks = [asyncio.Lock() for _ in transports]
    counters: list[dict[str, Any]] = [
        {
            "received_packets": 0,
            "received_bytes": 0,
            "first_packet_seconds": None,
            "stream_errors": 0,
            "quiet_intervals": 0,
            "reconnections": 0,
            "reconnection_failures": 0,
        }
        for _ in transports
    ]
    samples: list[dict[str, Any]] = []
    cleanup: list[bool] = []

    async def consume(index: int, transport: Transport) -> None:
        values = counters[index]
        reconnect_at = time.monotonic() + reconnect_seconds if reconnect_seconds else math.inf
        try:
            async with locks[index]:
                await transport.connect()
            while True:
                if time.monotonic() >= reconnect_at:
                    async with locks[index]:
                        if not await transport.close():
                            values["stream_errors"] += 1
                        try:
                            await transport.connect()
                            values["reconnections"] += 1
                        except Exception:  # noqa: BLE001 - record failure without disclosing transport secrets
                            values["reconnection_failures"] += 1
                            return
                    reconnect_at = time.monotonic() + reconnect_seconds
                try:
                    size = await asyncio.wait_for(transport.receive(), timeout=5)
                except TimeoutError:
                    values["quiet_intervals"] += 1
                    continue
                if size:
                    values["received_packets"] += 1
                    values["received_bytes"] += size
                    if values["first_packet_seconds"] is None:
                        values["first_packet_seconds"] = time.monotonic() - started
        except Exception:  # noqa: BLE001 - record failure without disclosing transport secrets
            values["stream_errors"] += 1

    tasks = [asyncio.create_task(consume(i, t)) for i, t in enumerate(transports)]
    try:
        while time.monotonic() - started < duration:
            await asyncio.sleep(min(sample_seconds, duration - (time.monotonic() - started)))
            observations = []
            for index, transport in enumerate(transports):
                try:
                    async with locks[index]:
                        observations.append(await transport.sample())
                except Exception:  # noqa: BLE001 - record failure without disclosing transport secrets
                    observations.append({"sample_error": True})
            samples.append(
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "resources": await container_resources(container)
                    if container
                    else await resources(backend_pid),
                    "viewers": observations,
                }
            )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for transport in transports:
            try:
                cleanup.append(await transport.close())
            except Exception:  # noqa: BLE001 - record failure without disclosing transport secrets
                cleanup.append(False)
    elapsed = time.monotonic() - started
    for values in counters:
        values["received_bytes_per_second"] = values["received_bytes"] / elapsed
    healthy = not any(
        v.get("sample_error") for sample in samples for v in sample["viewers"]
    ) and all(
        v["received_packets"] and not v["stream_errors"] and not v["reconnection_failures"]
        for v in counters
    )
    cleanup_resources = await container_resources(container) if container else None
    resource_cleanup_status = "UNAVAILABLE"
    keys = ("owned_adb_forward_count", "transport_manifest_entries")
    if (
        baseline_resources is not None
        and cleanup_resources is not None
        and all(baseline_resources.get(key) == 0 for key in keys)
        and all(type(cleanup_resources.get(key)) is int for key in keys)
    ):
        resource_cleanup_status = (
            "PASS" if all(cleanup_resources[key] == 0 for key in keys) else "FAIL"
        )
    if resource_cleanup_status != "UNAVAILABLE":
        assert baseline_resources is not None and cleanup_resources is not None
        baseline_forwards = baseline_resources.get("adb_forward_count")
        final_forwards = cleanup_resources.get("adb_forward_count")
        if (
            type(baseline_forwards) is int
            and type(final_forwards) is int
            and final_forwards > baseline_forwards
        ):
            # A removed manifest cannot conceal a forwarding entry left behind.
            resource_cleanup_status = "FAIL"
    return {
        "status": "PASS"
        if healthy and all(cleanup) and resource_cleanup_status != "FAIL"
        else "FAIL",
        "duration_seconds": elapsed,
        "requested_seconds": duration,
        "viewers": counters,
        "samples": samples,
        "cleanup_verified": cleanup,
        "baseline_resources": baseline_resources,
        "cleanup_resources": cleanup_resources,
        "resource_cleanup_status": resource_cleanup_status,
        "resource_cleanup_scope": (
            "Fleet manifest, recorded ADB forwards and increases in total forwards; "
            "orphan processes unavailable. "
            "Requires zero owned baseline transports and no concurrent background workload. "
            "Shared or missing observations cannot establish this soak's resource cleanup."
        ),
        "measurement_scope": "encoded packets received; no browser decode or render",
        "unavailable": (
            ["adb_forward_count", "transport_manifest_entries"] if not container else []
        )
        + [
            "capture_fps",
            "decoded_fps",
            "rendered_fps",
            "end_to_end_latency",
            "browser_resources",
            "orphan_process_count",
        ],
    }


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("simulated", "live"), default="simulated")
    parser.add_argument("--minutes", type=float, default=15)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--sample-seconds", type=float, default=10)
    parser.add_argument("--reconnect-seconds", type=float, default=0)
    parser.add_argument("--viewers", type=int, choices=range(1, 17), default=1)
    parser.add_argument("--quality", choices=QUALITY, default="medium")
    parser.add_argument("--base", default="http://127.0.0.1:9000")
    parser.add_argument("--origin", default="http://127.0.0.1:8088")
    parser.add_argument("--device")
    parser.add_argument("--token-env", default="AFM_TOKEN")
    parser.add_argument("--backend-pid", type=int)
    parser.add_argument("--container", help="Existing backend container; read-only sampling")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def main() -> int:
    args = arguments()
    if args.mode == "live" and not args.device:
        raise ValueError("Explicit registered device required")
    transports: list[Transport] = [
        LiveTransport(
            args.base,
            os.environ.get(args.token_env, ""),
            args.device,
            args.quality,
            args.origin,
        )
        if args.mode == "live"
        else SimulatedTransport(QUALITY[args.quality]["max_fps"])
        for _ in range(args.viewers)
    ]
    result = await run_soak(
        transports,
        args.seconds if args.seconds is not None else args.minutes * 60,
        args.sample_seconds,
        args.reconnect_seconds,
        args.backend_pid,
        args.container,
    )
    result.update(
        mode=args.mode,
        quality=args.quality,
        synthetic=args.mode == "simulated",
        requested_viewers=args.viewers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "duration_seconds": result["duration_seconds"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (ValueError, OSError):
        raise SystemExit("Soak configuration or output failure; details suppressed") from None
