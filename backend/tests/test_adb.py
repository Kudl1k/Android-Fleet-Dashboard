import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.adb.subprocess import SubprocessAdbClient
from android_fleet.devices.models import DeviceState

DEVICE_LIST_OUTPUT = (Path(__file__).parent / "fixtures" / "adb_devices.txt").read_bytes()


@pytest.mark.asyncio
async def test_remote_arguments_are_quoted() -> None:
    process = AsyncMock()
    process.communicate.return_value = (b"ok", b"")
    process.returncode = 0

    async def read_stdout(size: int) -> bytes:
        output, _ = await process.communicate()
        if getattr(read_stdout, "done", False):
            return b""
        read_stdout.done = True  # type: ignore[attr-defined]
        return output

    async def read_stderr(size: int) -> bytes:
        _, output = await process.communicate()
        if getattr(read_stderr, "done", False):
            return b""
        read_stderr.done = True  # type: ignore[attr-defined]
        return output

    process.stdout.read.side_effect = read_stdout
    process.stderr.read.side_effect = read_stderr
    with patch("asyncio.create_subprocess_exec", return_value=process) as spawn:
        client = SubprocessAdbClient(server_host="adb-host", server_port=5038)
        result = await client.shell("serial", ("echo", "$(touch /tmp/nope)", "two words"))
    assert result.stdout == "ok"
    assert spawn.call_args.args == (
        "adb",
        "-H",
        "adb-host",
        "-P",
        "5038",
        "-s",
        "serial",
        "shell",
        "echo '$(touch /tmp/nope)' 'two words'",
    )


@pytest.mark.asyncio
async def test_device_states_and_unknown_transport() -> None:
    process = AsyncMock()
    process.communicate.return_value = (
        DEVICE_LIST_OUTPUT,
        b"",
    )
    process.returncode = 0

    async def read_stdout(size: int) -> bytes:
        output, _ = await process.communicate()
        if getattr(read_stdout, "done", False):
            return b""
        read_stdout.done = True  # type: ignore[attr-defined]
        return output

    async def read_stderr(size: int) -> bytes:
        _, output = await process.communicate()
        if getattr(read_stderr, "done", False):
            return b""
        read_stderr.done = True  # type: ignore[attr-defined]
        return output

    process.stdout.read.side_effect = read_stdout
    process.stderr.read.side_effect = read_stderr
    with patch("asyncio.create_subprocess_exec", return_value=process):
        result = await SubprocessAdbClient().list_devices()
    assert result == {
        "a": DeviceState.ONLINE,
        "b": DeviceState.OFFLINE,
        "c": DeviceState.UNAUTHORIZED,
        "d": DeviceState.ERROR,
    }


@pytest.mark.asyncio
async def test_timeout_kills_and_reaps_process() -> None:
    client = SubprocessAdbClient(executable=sys.executable)
    client._prefix = [sys.executable]
    result = await client._run(["-c", "import time; time.sleep(30)"], 0.05)
    assert result.timeout
    assert result.exit_code is not None
    assert result.duration < 5


@pytest.mark.asyncio
async def test_cancellation_kills_and_reaps_process() -> None:
    process = AsyncMock()
    process.returncode = None
    finished = asyncio.Event()

    async def communicate() -> tuple[bytes, bytes]:
        await finished.wait()
        return b"", b""

    def kill() -> None:
        process.returncode = -9
        finished.set()

    process.kill = kill
    process.communicate.side_effect = communicate

    async def read_stdout(size: int) -> bytes:
        output, _ = await process.communicate()
        if getattr(read_stdout, "done", False):
            return b""
        read_stdout.done = True  # type: ignore[attr-defined]
        return output

    async def read_stderr(size: int) -> bytes:
        _, output = await process.communicate()
        if getattr(read_stderr, "done", False):
            return b""
        read_stderr.done = True  # type: ignore[attr-defined]
        return output

    process.stdout.read.side_effect = read_stdout
    process.stderr.read.side_effect = read_stderr
    with patch("asyncio.create_subprocess_exec", return_value=process):
        task = asyncio.create_task(SubprocessAdbClient().shell("serial", ("id",)))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_fake_root_nonroot_offline_and_malformed() -> None:
    client = FakeAdbClient()
    assert (await client.shell("pixel-rooted", ("su", "-c", "id -u"))).stdout == "0\n"
    assert (await client.shell("pixel-stock", ("su", "-c", "id -u"))).exit_code == 1
    assert (await client.shell("pixel-offline", ("getprop",))).exit_code == 1
    assert "???" in (await client.shell("pixel-malformed", ("dumpsys", "battery"))).stdout
    listed = await client.list_devices()
    listed.clear()
    assert len(await client.list_devices()) == 4


def test_mdns_parser_retains_pairing_and_canonicalizes_connect_identity() -> None:
    from android_fleet.adb.subprocess import parse_mdns

    parsed = parse_mdns(
        "List of discovered mdns services\n"
        "device _adb-tls-connect._tcp. 192.0.2.1:4000\n"
        "device._adb-tls-pairing._tcp.local. _adb-tls-pairing._tcp [2001:db8::1]:4001\n"
        "invalid _adb-tls-connect._tcp 192.0.2.1:bad\n"
        "invalid _adb-tls-connect._tcp 192.0.2.1:99999\n"
        "garbage\n"
    )
    assert len(parsed) == 2
    assert parsed[0].name == "device._adb-tls-connect._tcp"
    assert parsed[1].name == "device._adb-tls-pairing._tcp"
    assert parsed[1].address == "[2001:db8::1]:4001"


@pytest.mark.asyncio
async def test_disconnect_and_mdns_use_targeted_argv() -> None:
    process = AsyncMock()
    process.communicate.return_value = (b"", b"")
    process.returncode = 0

    async def read_stdout(size: int) -> bytes:
        output, _ = await process.communicate()
        if getattr(read_stdout, "done", False):
            return b""
        read_stdout.done = True  # type: ignore[attr-defined]
        return output

    async def read_stderr(size: int) -> bytes:
        _, output = await process.communicate()
        if getattr(read_stderr, "done", False):
            return b""
        read_stderr.done = True  # type: ignore[attr-defined]
        return output

    process.stdout.read.side_effect = read_stdout
    process.stderr.read.side_effect = read_stderr
    with patch("asyncio.create_subprocess_exec", return_value=process) as spawn:
        client = SubprocessAdbClient()
        await client.disconnect("192.0.2.1:5555")
        assert spawn.call_args.args[-2:] == ("disconnect", "192.0.2.1:5555")
        assert await client.mdns_services() == ()
        assert spawn.call_args.args[-2:] == ("mdns", "services")


@pytest.mark.parametrize(
    "endpoint",
    [
        "-evil:5555",
        "host;option:5555",
        "host/path:5555",
        "a..b:5555",
        "[2001:db8::1:5555",
        "2001:db8::1]:5555",
        "[[2001:db8::1]]:5555",
        "[hostname]:5555",
        "[192.0.2.1]:5555",
        "fe80::1%eth0:5555",
        "hostname:+5555",
        "hostname:５５５５",
        "hostname:-1",
    ],
)
def test_mdns_ignores_invalid_hosts_and_endpoints(endpoint: str) -> None:
    from android_fleet.adb.subprocess import parse_mdns

    assert parse_mdns(f"valid _adb-tls-connect._tcp {endpoint}") == ()


@pytest.mark.parametrize("instance", ["bad.name", "bad/name", "bad;name", "évil", "x" * 129])
def test_mdns_ignores_invalid_instance_names(instance: str) -> None:
    from android_fleet.adb.subprocess import parse_mdns

    assert parse_mdns(f"{instance} _adb-tls-connect._tcp 192.0.2.1:5555") == ()


def test_mdns_case_matches_registry_and_normalizes_hosts() -> None:
    from android_fleet.adb.subprocess import parse_mdns

    records = parse_mdns(
        "ADB-Pixel_1._ADB-TLS-CONNECT._TCP.LOCAL. _ADB-TLS-CONNECT._TCP. PHONE.Example.:5555\n"
        "ADB-Pixel_1._adb-tls-connect._tcp _adb-tls-connect._tcp phone.example:5555\n"
        "IPv6 _adb-tls-connect._tcp [2001:DB8::1]:5555\n"
    )
    assert len(records) == 2
    assert records[0].name == "adb-pixel_1._adb-tls-connect._tcp"
    assert records[0].host == "phone.example"
    assert records[1].address == "[2001:db8::1]:5555"


@pytest.mark.asyncio
async def test_adapter_disables_server_mdns_autoconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADB_MDNS_AUTO_CONNECT", "1")
    process = AsyncMock()
    process.communicate.return_value = (b"", b"")
    process.returncode = 0

    async def read_stdout(size: int) -> bytes:
        output, _ = await process.communicate()
        if getattr(read_stdout, "done", False):
            return b""
        read_stdout.done = True  # type: ignore[attr-defined]
        return output

    async def read_stderr(size: int) -> bytes:
        _, output = await process.communicate()
        if getattr(read_stderr, "done", False):
            return b""
        read_stderr.done = True  # type: ignore[attr-defined]
        return output

    process.stdout.read.side_effect = read_stdout
    process.stderr.read.side_effect = read_stderr
    with patch("asyncio.create_subprocess_exec", return_value=process) as spawn:
        await SubprocessAdbClient().connect("192.0.2.1:5555")
    assert spawn.call_args.kwargs["env"]["ADB_MDNS_AUTO_CONNECT"] == "0"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_oversized_output_is_bounded_and_reaped(stream: str) -> None:
    client = SubprocessAdbClient(executable=sys.executable)
    client._prefix = [sys.executable]
    script = (
        f"import sys,time; sys.{stream}.buffer.write(b'x'*4000000); "
        f"sys.{stream}.flush(); time.sleep(30)"
    )
    with pytest.raises(RuntimeError, match="output limit"):
        await asyncio.wait_for(client._run(["-c", script], 5), 2)


async def test_forward_inspection_is_bounded_and_rejects_unknown_output() -> None:
    from android_fleet.execution.models import CommandResult

    client = SubprocessAdbClient()
    with patch.object(client, "_run", new_callable=AsyncMock) as run:
        run.return_value = CommandResult(
            stdout="fixture tcp:1234 localabstract:scrcpy_01234567\n\n"
        )
        assert await client.list_forwards() == (
            ("fixture", "tcp:1234", "localabstract:scrcpy_01234567"),
        )
        run.assert_awaited_with(["forward", "--list"], 10.0)
        run.return_value = CommandResult(stdout="unexpected output")
        with pytest.raises(RuntimeError, match="Malformed"):
            await client.list_forwards()
        run.return_value = CommandResult(timeout=True)
        with pytest.raises(RuntimeError, match="inspect"):
            await client.list_forwards()


async def test_pairing_code_stdin_and_redaction() -> None:
    process = AsyncMock()
    process.returncode = 0
    process.stdout.read.side_effect = [b"Successfully paired with host; code 123456", b""]
    process.stderr.read.side_effect = [b"123456", b""]
    from unittest.mock import Mock

    process.stdin.write = Mock()
    process.stdin.close = Mock()
    with patch("asyncio.create_subprocess_exec", return_value=process) as spawn:
        result = await SubprocessAdbClient().pair("192.168.1.2:37001", "123456")
    assert "123456" not in spawn.call_args.args
    process.stdin.write.assert_called_once_with(b"123456\n")
    assert result.stdout == "paired"
    assert not result.stderr
    with pytest.raises(ValueError):
        await SubprocessAdbClient().pair("192.168.1.2:37001", "wrong")


async def test_local_pty_controls_resize_and_cleanup() -> None:
    import os

    from android_fleet.adb.subprocess import AdbTerminal

    master, slave = os.openpty()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        'import tty,os; tty.setraw(0); os.write(1,b"ready"); os.write(1,os.read(0,3))',
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)
    transport = AdbTerminal(process, master)
    try:
        assert await asyncio.wait_for(transport.read(), 3) == b"ready"
        await transport.resize(120, 40)
        await transport.write(b"\x03ab")
        assert await asyncio.wait_for(transport.read(), 3) == b"\x03ab"
    finally:
        await transport.close()
    assert process.returncode is not None
    assert transport.closed


async def test_resize_notifies_owned_client_without_controlling_terminal() -> None:
    import os

    from android_fleet.adb.subprocess import AdbTerminal

    master, slave = os.openpty()
    script = "\n".join(
        (
            "import os",
            "import signal",
            "",
            "def on_resize(_signum, _frame):",
            "    size = os.get_terminal_size(0)",
            '    value = f"{size.lines} {size.columns}".encode()',
            "    os.write(1, value)",
            "",
            "signal.signal(signal.SIGWINCH, on_resize)",
            'os.write(1, b"ready")',
            "signal.pause()",
        )
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", script, stdin=slave, stdout=slave, stderr=slave
    )
    os.close(slave)
    transport = AdbTerminal(process, master)
    try:
        assert await asyncio.wait_for(transport.read(), 3) == b"ready"
        await transport.resize(120, 40)
        assert await asyncio.wait_for(transport.read(), 3) == b"40 120"
    finally:
        await transport.close()
