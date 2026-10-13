"""Screen lifecycle and security checks using an isolated video transport."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from android_fleet.devices.models import DeviceState
from android_fleet.screen.bridge import VideoPacket
from android_fleet.screen.manager import ScreenManager
from android_fleet.screen.models import InputEvent, ScreenConfig, SessionState
from android_fleet.security import ROLE_PERMISSIONS, Actor


class Stream:
    width = 100
    height = 200

    def __init__(self):
        self.close = AsyncMock()
        self.send_input = AsyncMock()
        self.frames = asyncio.Queue()

    async def packets(self):
        while True:
            yield await self.frames.get()


@pytest.fixture
async def manager():
    stream = Stream()
    security = SimpleNamespace(audit=AsyncMock())

    async def authorize(actor, device_id, permission):
        if (
            permission not in actor.permissions
            or actor.identity == "anonymous"
            or (actor.device_ids is not None and device_id not in actor.device_ids)
        ):
            raise HTTPException(403)

    security.authorize_device = authorize
    fleet = SimpleNamespace(
        get=lambda _: SimpleNamespace(
            state=DeviceState.ONLINE, serial="fake", capabilities={"adb_shell"}, sdk=36
        )
    )
    settings = SimpleNamespace(
        screen_max_sessions=4,
        screen_max_per_device=2,
        screen_max_per_user=2,
        screen_queue_frames=3,
        screen_idle_seconds=0.05,
    )
    bridge = SimpleNamespace(start=AsyncMock(return_value=stream), recover=AsyncMock())
    obj = ScreenManager(None, fleet, security, settings, bridge=bridge)
    yield obj
    await obj.close()


def actor(name="operator", role="operator", scope=None):
    return Actor(name, role, ROLE_PERMISSIONS[role], scope)


async def ready(manager, owner=None):
    session = await manager.create("phone", owner or actor(), ScreenConfig())
    await asyncio.sleep(0)
    ticket = await manager.ticket(session, session.owner)
    await manager.attach(session.id, ticket["ticket"])
    return session


async def test_lifecycle_restart_and_cleanup(manager):
    await manager.start()
    manager.bridge.recover.assert_awaited_once()
    session = await ready(manager)
    assert session.state == SessionState.STREAMING
    await manager.acquire(session, session.owner)
    await manager.stop(session)
    assert session.state == SessionState.STOPPED and not session.control
    manager.bridge.start.return_value.close.assert_awaited_once()
    assert manager.metrics()["active_sessions"] == 0
    assert not manager.tickets


async def test_ownership_scope_view_only_and_exclusive(manager):
    session = await ready(manager)
    with pytest.raises(HTTPException) as exc:
        await manager.get(session.id, actor("other"))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        await manager.create("phone", actor(scope=frozenset({"other"})), ScreenConfig())
    with pytest.raises(HTTPException):
        await manager.create("phone", actor("anonymous", "viewer"), ScreenConfig())
    await manager.acquire(session, session.owner)
    second = await ready(manager, actor("second"))
    with pytest.raises(HTTPException) as exc:
        await manager.acquire(second, second.owner)
    assert exc.value.status_code == 409
    await manager.release(session)
    await manager.acquire(second, second.owner)
    await manager.release(second)
    second.owner = actor("viewer", "viewer")
    with pytest.raises(HTTPException):
        await manager.acquire(second, second.owner)
    with pytest.raises(HTTPException):
        await manager.input(second, second.owner, InputEvent(type="nav", key="home"))
    second.stream.send_input.assert_not_awaited()


async def test_ticket_single_use_expired_and_cross_session(manager):
    session = await ready(manager)
    session.attached = False
    ticket = await manager.ticket(session, session.owner)
    with pytest.raises(HTTPException):
        await manager.attach("another", ticket["ticket"])
    with pytest.raises(HTTPException):
        await manager.attach(session.id, ticket["ticket"])
    ticket = await manager.ticket(session, session.owner)
    manager.tickets[ticket["ticket"]] = session.id, session.owner, time.time() - 1
    with pytest.raises(HTTPException):
        await manager.attach(session.id, ticket["ticket"])


async def test_input_rate_and_dimensions(manager):
    session = await ready(manager)
    event = InputEvent(type="nav", key="back")
    with pytest.raises(HTTPException):
        await manager.input(session, session.owner, event)
    await manager.acquire(session, session.owner)
    for _ in range(120):
        await manager.input(session, session.owner, event)
    with pytest.raises(HTTPException) as exc:
        await manager.input(session, session.owner, event)
    assert exc.value.status_code == 429
    session.rate_count = 0
    with pytest.raises(HTTPException) as exc:
        await manager.input(
            session,
            session.owner,
            InputEvent(type="pointer", action="down", x=1, y=1, width=201, height=100),
        )
    assert exc.value.status_code == 409


async def test_limits_offline_idle(manager):
    await ready(manager)
    await ready(manager)
    with pytest.raises(HTTPException) as exc:
        await ready(manager)
    assert exc.value.status_code == 429
    manager.fleet.get = lambda _: SimpleNamespace(state=DeviceState.DISCONNECTED)
    with pytest.raises(HTTPException) as exc:
        await manager.create("other", actor(), ScreenConfig())
    assert exc.value.status_code == 409
    manager.fleet.get = lambda _: SimpleNamespace(
        state=DeviceState.ONLINE, serial="fake", capabilities={"adb_shell"}, sdk=36
    )
    await manager.start()
    await asyncio.sleep(1.1)
    assert all(s.state == SessionState.TIMED_OUT for s in manager.sessions.values())


async def test_bounded_drop_to_keyframe(manager):
    session = await ready(manager)
    while not session.queue.empty():
        session.queue.get_nowait()

    def packet(config=False, keyframe=False):
        return VideoPacket(b"video", 1, config=config, keyframe=keyframe)

    for _ in range(8):
        await session.stream.frames.put(packet())
    await asyncio.sleep(0)
    assert session.queue.qsize() <= 3 and session.dropped_frames > 0
    await session.stream.frames.put(packet(config=True))
    await session.stream.frames.put(packet(keyframe=True))
    await asyncio.sleep(0)
    assert not session.dropping and session.queue.qsize() == 2


async def test_release_cancels_held_pointer_keys_and_rotation(manager):
    session = await ready(manager)
    await manager.acquire(session, session.owner)
    await manager.input(
        session,
        session.owner,
        InputEvent(type="pointer", action="down", x=10, y=10, width=100, height=200),
    )
    await manager.input(session, session.owner, InputEvent(type="key", action="down", keycode=59))
    await manager.release(session)
    calls = [call.args[0] for call in session.stream.send_input.await_args_list]
    assert calls[-2]["action"] == "cancel"
    assert calls[-1] == {"type": "key", "action": "up", "keycode": 59}
    assert not session.control and not session.held_keys and session.pointer is None


async def test_global_and_user_limits_independent(manager):
    manager.settings.screen_max_per_device = 10
    manager.settings.screen_max_per_user = 1
    await ready(manager)
    with pytest.raises(HTTPException) as exc:
        await manager.create("second-device", actor(), ScreenConfig())
    assert exc.value.status_code == 429
    manager.settings.screen_max_per_user = 10
    manager.settings.screen_max_sessions = 1
    with pytest.raises(HTTPException) as exc:
        await manager.create("second-device", actor("another"), ScreenConfig())
    assert exc.value.status_code == 429


async def test_offline_watchdog_stops_static_stream(manager):
    session = await ready(manager)
    await manager.acquire(session, session.owner)
    manager.settings.screen_idle_seconds = 30
    manager.fleet.get = lambda _: SimpleNamespace(state=DeviceState.DISCONNECTED)
    await manager.start()
    await asyncio.sleep(1.1)
    assert session.state == SessionState.FAILED
    assert session.termination_reason == "device_offline"
    assert not session.control
    manager.bridge.start.return_value.close.assert_awaited()


async def test_reconnect_bounded_releases_control_and_start_failure(manager):
    session = await ready(manager)
    await manager.acquire(session, session.owner)
    session.task.cancel()
    await asyncio.gather(session.task, return_exceptions=True)
    original = session.stream
    manager.bridge.start = AsyncMock(side_effect=RuntimeError("crashed"))
    session.task = asyncio.create_task(manager._run(session, "fake"))
    await asyncio.sleep(0.05)
    assert session.state == SessionState.RECONNECTING and not session.control
    await session.task
    assert session.state == SessionState.FAILED and session.reconnect_attempts == 2
    original.close.assert_awaited()
    assert manager.bridge.start.await_count == 3
    assert manager.failures == 1


async def test_successful_reconnect_notifies_viewer_without_control(manager):
    session = await ready(manager)
    session.reconnect_attempts = 1
    session.state = SessionState.RECONNECTING
    session.attached = True
    session.queue.put_nowait({"type": "status", "state": "reconnecting", "control": False})
    replacement = Stream()
    manager.bridge.start = AsyncMock(return_value=replacement)
    session.task = asyncio.create_task(manager._run(session, "fake"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    statuses = [item for item in list(session.queue._queue) if isinstance(item, dict)]
    assert any(
        item == {"type": "status", "state": "streaming", "control": False} for item in statuses
    )
    assert not session.control
    await manager.stop(session)


async def independent_session(manager, device_id, owner):
    stream = Stream()
    manager.bridge.start.return_value = stream
    session = await manager.create(device_id, owner, ScreenConfig())
    await asyncio.sleep(0)
    ticket = await manager.ticket(session, owner)
    await manager.attach(session.id, ticket["ticket"])
    return session, stream


def video_packet(data=b"frame", *, config=False, keyframe=False):
    return VideoPacket(data, 1, config=config, keyframe=keyframe)


async def test_two_viewers_have_independent_queues_and_teardown(manager):
    first, first_stream = await independent_session(manager, "phone", actor("first"))
    second, second_stream = await independent_session(manager, "phone", actor("second"))
    assert manager.metrics()["active_viewers"] == 2
    for _ in range(10):
        await first_stream.frames.put(video_packet())
    await second_stream.frames.put(video_packet(b"second", keyframe=True))
    await asyncio.sleep(0)
    assert first.dropped_frames > 0 and first.queue.qsize() <= 3
    assert second.dropped_frames == 0
    assert video_packet(b"second", keyframe=True).wire() in list(second.queue._queue)
    await manager.acquire(first, first.owner)
    await manager.stop(first, "browser_disconnected")
    assert not first.control and not first.attached and first.stream is None
    first_stream.close.assert_awaited_once()
    assert second.state == SessionState.STREAMING
    second_stream.close.assert_not_awaited()
    await manager.acquire(second, second.owner)
    await manager.stop(second, "browser_disconnected")
    second_stream.close.assert_awaited_once()
    assert manager.metrics()["active_viewers"] == 0


async def test_devices_have_independent_input_video_and_failure(manager):
    first, first_stream = await independent_session(manager, "phone", actor("first"))
    second, second_stream = await independent_session(manager, "tablet", actor("second"))
    await manager.acquire(first, first.owner)
    await manager.acquire(second, second.owner)
    await manager.input(second, second.owner, InputEvent(type="nav", key="back"))
    first_stream.send_input.assert_not_awaited()
    second_stream.send_input.assert_awaited_once_with(
        InputEvent(type="nav", key="back").model_dump(exclude_none=True)
    )
    with pytest.raises(HTTPException):
        await manager.input(first, second.owner, InputEvent(type="nav", key="home"))
    await first_stream.frames.put(video_packet(b"phone"))
    await second_stream.frames.put(video_packet(b"tablet"))
    await asyncio.sleep(0)
    assert video_packet(b"phone").wire() not in list(second.queue._queue)
    assert video_packet(b"tablet").wire() not in list(first.queue._queue)
    await manager.stop(first, "device_offline", SessionState.FAILED)
    assert second.control and second.state == SessionState.STREAMING
    second_stream.close.assert_not_awaited()


async def test_rotated_geometry_rejects_stale_dimensions_and_updates_metadata(manager):
    session = await ready(manager)
    await manager.acquire(session, session.owner)
    while not session.queue.empty():
        session.queue.get_nowait()
    with pytest.raises(HTTPException) as exc:
        await manager.input(
            session,
            session.owner,
            InputEvent(type="pointer", action="down", x=10, y=10, width=200, height=100),
        )
    assert exc.value.status_code == 409
    session.stream.width, session.stream.height = 200, 100
    await session.stream.frames.put(video_packet(b"rotated", config=True))
    await asyncio.sleep(0)
    assert session.queue.get_nowait() == {
        "type": "metadata",
        "width": 200,
        "height": 100,
        "codec": "h264",
    }
    with pytest.raises(HTTPException) as exc:
        await manager.input(
            session,
            session.owner,
            InputEvent(type="pointer", action="down", x=10, y=10, width=100, height=200),
        )
    assert exc.value.status_code == 409
    await manager.input(
        session,
        session.owner,
        InputEvent(type="pointer", action="down", x=150, y=10, width=200, height=100),
    )
    while not session.queue.empty():
        session.queue.get_nowait()
    session.stream.width, session.stream.height = 100, 200
    await session.stream.frames.put(video_packet(b"portrait", config=True))
    await asyncio.sleep(0)
    cancel = session.stream.send_input.await_args_list[-1].args[0]
    assert cancel["action"] == "cancel"
    assert (cancel["width"], cancel["height"], cancel["x"]) == (100, 200, 99)
    assert session.pointer is None
    assert session.queue.get_nowait() == {
        "type": "metadata",
        "width": 100,
        "height": 200,
        "codec": "h264",
    }


async def test_slow_release_does_not_block_other_devices_or_allow_ownership_overlap(manager):
    first, first_stream = await independent_session(manager, "phone", actor("first"))
    other, _ = await independent_session(manager, "tablet", actor("other"))
    contender, _ = await independent_session(manager, "phone", actor("contender"))
    await manager.acquire(first, first.owner)
    first.held_keys.add(59)
    entered, proceed = asyncio.Event(), asyncio.Event()

    async def delayed_input(payload):
        entered.set()
        await proceed.wait()

    first_stream.send_input.side_effect = delayed_input
    release = asyncio.create_task(manager.release(first))
    await entered.wait()
    try:
        async with asyncio.timeout(0.5):
            await manager.acquire(other, other.owner)
        with pytest.raises(HTTPException) as exc:
            await manager.acquire(contender, contender.owner)
        assert exc.value.status_code == 409
    finally:
        proceed.set()
        await release
    await manager.acquire(contender, contender.owner)


async def test_cleanup_failure_releases_reservation_and_counts_failure(manager):
    session, stream = await independent_session(manager, "phone", actor())
    await manager.acquire(session, session.owner)
    stream.close.side_effect = RuntimeError("cleanup failed")
    await asyncio.gather(manager.stop(session), manager.stop(session))
    assert session.state == SessionState.STOPPED
    assert not session.control and not session.attached and session.stream is None
    assert manager.cleanup_failures == 1
    stream.close.assert_awaited_once()
    assert manager.metrics()["active_sessions"] == 0


async def test_capacity_rejection_metric_counts_only_resource_rejections(manager):
    manager.settings.screen_max_sessions = 1
    await ready(manager)
    with pytest.raises(HTTPException) as exc:
        await manager.create("tablet", actor("second"), ScreenConfig())
    assert exc.value.status_code == 429
    assert manager.metrics()["resource_limit_rejections"] == 1


async def test_drop_counter_excludes_configuration_and_metadata(manager):
    session = await ready(manager)
    # Startup metadata is queued; add config and one actual encoded frame.
    await session.stream.frames.put(video_packet(b"configuration", config=True))
    await session.stream.frames.put(video_packet(b"first"))
    await asyncio.sleep(0)
    assert session.queue.full()
    await session.stream.frames.put(video_packet(b"second"))
    await asyncio.sleep(0)
    # One queued frame plus the incoming delta discarded while awaiting IDR.
    assert session.dropped_frames == 2
    assert manager.metrics()["dropped_frames"] == 2
    await session.stream.frames.put(video_packet(b"replacement-config", config=True))
    await asyncio.sleep(0)
    assert session.dropped_frames == 2
    await session.stream.frames.put(video_packet(b"idr", keyframe=True))
    await asyncio.sleep(0)
    assert not session.dropping and session.queue.qsize() == 2
