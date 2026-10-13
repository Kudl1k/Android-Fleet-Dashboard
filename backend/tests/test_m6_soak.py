"""No hardware, credentials or input are needed by the soak regression suite."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "m6_soak", Path(__file__).parents[2] / "scripts/m6_soak.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.asyncio
async def test_soak_reconnects_isolates_and_cleans_viewers() -> None:
    viewers = [module.SimulatedTransport(100), module.SimulatedTransport(50)]
    result = await module.run_soak(viewers, 0.16, 0.04, 0.06)
    assert result["status"] == "PASS"
    assert result["cleanup_verified"] == [True, True]
    assert all(v["reconnections"] >= 1 for v in result["viewers"])
    assert all(v["received_packets"] > 0 for v in result["viewers"])
    assert all(v.task is None and v.queue.empty() for v in viewers)
    assert "decoded_fps" in result["unavailable"]


@pytest.mark.asyncio
async def test_slow_consumer_queue_is_bounded() -> None:
    import asyncio

    transport = module.SimulatedTransport(1000)
    await transport.connect()
    await asyncio.sleep(0.04)
    assert transport.queue.qsize() == 8
    assert transport.dropped > 0
    assert await transport.close()


@pytest.mark.asyncio
async def test_failure_report_still_cleans_every_transport() -> None:
    class Broken(module.SimulatedTransport):
        async def connect(self) -> None:
            raise RuntimeError("private secret must never appear in results")

    result = await module.run_soak([Broken(), module.SimulatedTransport(100)], 0.04, 0.02)
    assert result["status"] == "FAIL"
    assert result["cleanup_verified"] == [True, True]
    assert "private secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("duration,interval", [(0, 1), (1, 0), (float("nan"), 1)])
async def test_invalid_duration(duration: float, interval: float) -> None:
    with pytest.raises(ValueError):
        await module.run_soak([module.SimulatedTransport()], duration, interval)


@pytest.mark.parametrize(
    "base",
    [
        "http://example.com",
        "http://secret@localhost:9000",
        "https://localhost",
        "http://localhost/?token=secret",
    ],
)
def test_credentials_cannot_be_forwarded(base: str) -> None:
    with pytest.raises(ValueError):
        module.LiveTransport(base, "token", "device", "low", "http://localhost")


@pytest.mark.asyncio
async def test_unavailable_resources_are_null() -> None:
    assert await module.resources(None) == {
        "rss_bytes": None,
        "cpu_percent": None,
        "open_fds": None,
    }


@pytest.mark.asyncio
async def test_live_transport_only_sends_liveness_and_never_returns_content() -> None:
    class Socket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, message: str) -> None:
            self.sent.append(message)

        async def recv(self) -> bytes:
            return b"private video content"

    transport = module.LiveTransport(
        "http://127.0.0.1:9000", "secret", "device", "low", "http://127.0.0.1:8088"
    )
    transport.socket = Socket()
    assert await transport.receive() == len(b"private video content")
    heartbeat = __import__("asyncio").create_task(transport.keep_alive())
    await __import__("asyncio").sleep(0)
    assert transport.socket.sent == ['{"type":"ping"}']
    heartbeat.cancel()
    await __import__("asyncio").gather(heartbeat, return_exceptions=True)
    assert await transport.receive() == len(b"private video content")
    assert len(transport.socket.sent) == 1


@pytest.mark.asyncio
async def test_outer_cancellation_reaps_producers() -> None:
    import asyncio

    transport = module.SimulatedTransport(100)
    task = asyncio.create_task(module.run_soak([transport], 60, 10))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.task is None
    assert transport.queue.empty()


@pytest.mark.asyncio
async def test_quiet_interval_is_not_stream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    original = module.asyncio.wait_for
    interrupted = False

    async def quiet_once(awaitable: object, timeout: float) -> object:
        nonlocal interrupted
        if timeout == 5 and not interrupted:
            interrupted = True
            awaitable.close()  # type: ignore[attr-defined]
            raise TimeoutError
        return await original(awaitable, timeout)

    monkeypatch.setattr(module.asyncio, "wait_for", quiet_once)
    result = await module.run_soak([module.SimulatedTransport(100)], 0.04, 0.02)
    assert result["status"] == "PASS"
    assert result["viewers"][0]["quiet_intervals"] == 1
    assert result["viewers"][0]["stream_errors"] == 0


@pytest.mark.asyncio
async def test_live_health_checks_and_statistics_allowlist() -> None:
    class Live(module.LiveTransport):
        async def request(self, method: str, path: str, body: object = None) -> object:
            if path == "/ready":
                return {"status": "ready"}
            return {
                "state": "streaming",
                "statistics": {
                    "bytes_transferred": 123,
                    "input": "secret",
                    "startup_seconds": None,
                },
            }

    transport = Live("http://localhost:9000", "token", "device", "low", "http://localhost")
    assert await transport.sample() == {"bytes_transferred": 123}


@pytest.mark.asyncio
async def test_optional_longer_run_requires_bounded_sampling() -> None:
    with pytest.raises(ValueError, match="10000"):
        await module.run_soak([module.SimulatedTransport()], 10001, 1)


@pytest.mark.asyncio
async def test_container_sampling_uses_read_only_argv_and_redacts_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    calls: list[tuple[str, ...]] = []

    async def command(argv: tuple[str, ...], timeout: float = 15) -> bytes:
        calls.append(argv)
        if argv[1] == "stats":
            return json.dumps({"CPUPerc": "12.34%", "Name": "secret"}).encode()
        return json.dumps(
            {
                "rss_bytes": 4096,
                "open_fds": 12,
                "adb_forward_count": 1,
                "transport_manifest_entries": 1,
                "secret": "private",
            }
        ).encode()

    monkeypatch.setattr(module, "command_output", command)
    result = await module.container_resources("android-fleet-backend-1")
    assert result["cpu_percent"] == 12.34
    assert result["rss_bytes"] == 4096
    assert result["adb_forward_count"] == 1
    assert result["orphan_process_count"] is None
    assert "private" not in str(result) and "secret" not in str(result)
    assert {call[1] for call in calls} == {"stats", "exec"}
    assert "SubprocessAdbClient" in calls[0][-1]
    assert "list_forwards" in calls[0][-1]


@pytest.mark.asyncio
async def test_container_resource_failures_remain_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def command(argv: tuple[str, ...], timeout: float = 15) -> bytes:
        raise RuntimeError("private command error")

    monkeypatch.setattr(module, "command_output", command)
    result = await module.container_resources("backend")
    assert all(value is None for value in result.values())
    with pytest.raises(ValueError):
        await module.container_resources("--privileged")


@pytest.mark.asyncio
async def test_resource_subprocess_timeout_reaps_child() -> None:
    import sys

    with pytest.raises(TimeoutError):
        await module.command_output((sys.executable, "-c", "import time; time.sleep(60)"), 0.02)


@pytest.mark.asyncio
async def test_resource_subprocess_output_is_bounded() -> None:
    import sys

    with pytest.raises(ValueError, match="limit"):
        await module.command_output((sys.executable, "-c", "print('x'*100000)"))


def test_container_sampler_embedded_program_is_valid_python() -> None:
    compile(module.CONTAINER_SAMPLE, "container_sample", "exec")
    assert "shell(" not in module.CONTAINER_SAMPLE
    assert "kill(" not in module.CONTAINER_SAMPLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "baseline,final,expected,overall",
    [
        ((0, 0), (0, 0), "PASS", "PASS"),
        ((0, 0), (1, 1), "FAIL", "FAIL"),
        ((0, 0), (0, 1), "FAIL", "FAIL"),
        ((1, 1), (1, 1), "UNAVAILABLE", "PASS"),
        ((None, 0), (0, 0), "UNAVAILABLE", "PASS"),
        ((0, 0), (None, 0), "UNAVAILABLE", "PASS"),
    ],
)
async def test_resource_cleanup_requires_empty_comparable_baseline(
    monkeypatch: pytest.MonkeyPatch,
    baseline: tuple[int | None, int | None],
    final: tuple[int | None, int | None],
    expected: str,
    overall: str,
) -> None:
    observations = iter((baseline, (1, 1), final))

    async def sample(container: str) -> dict[str, int | None]:
        forwards, manifest = next(observations)
        return {"owned_adb_forward_count": forwards, "transport_manifest_entries": manifest}

    monkeypatch.setattr(module, "container_resources", sample)
    result = await module.run_soak(
        [module.SimulatedTransport(100)], 0.03, 0.03, container="backend"
    )
    assert result["resource_cleanup_status"] == expected
    assert result["status"] == overall
    assert result["baseline_resources"]["owned_adb_forward_count"] == baseline[0]
    assert result["cleanup_resources"]["transport_manifest_entries"] == final[1]
    assert "background workload" in result["resource_cleanup_scope"]


@pytest.mark.asyncio
async def test_erased_manifest_cannot_conceal_orphan_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter((0, 1, 1))

    async def sample(container: str) -> dict[str, int]:
        return {
            "owned_adb_forward_count": 0,
            "transport_manifest_entries": 0,
            "adb_forward_count": next(observations),
        }

    monkeypatch.setattr(module, "container_resources", sample)
    result = await module.run_soak(
        [module.SimulatedTransport(100)], 0.03, 0.03, container="backend"
    )
    assert result["resource_cleanup_status"] == "FAIL"
    assert result["status"] == "FAIL"
