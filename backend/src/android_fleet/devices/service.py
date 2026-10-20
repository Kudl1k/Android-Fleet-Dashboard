"""Application-owned persistent inventory and disposable runtime observations."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic

from android_fleet.adb.base import AdbClient
from android_fleet.adb.connection import ConnectionManager
from android_fleet.adb.connection_models import ConnectionObservation
from android_fleet.devices.models import ConnectionType, Device, DeviceCapability, DeviceState
from android_fleet.devices.probe import DeviceProbe, parse_getprop
from android_fleet.devices.registry import DeviceNotFound, SQLiteDeviceRegistry
from android_fleet.devices.registry_models import DeviceRegistration, RegisteredDevice
from android_fleet.discovery.models import DiscoveredDevice, DiscoverySnapshot
from android_fleet.discovery.service import DiscoveryError, DiscoveryService, discovered_devices
from android_fleet.metrics.collection import MetricPipeline
from android_fleet.metrics.history import HistoryError, MetricHistoryStore
from android_fleet.metrics.models import MetricSnapshot


class DeviceUnavailable(RuntimeError):
    pass


class FleetService:
    def __init__(
        self,
        adb: AdbClient,
        registry: SQLiteDeviceRegistry,
        history: MetricHistoryStore,
        *,
        enable_mdns: bool = False,
        seed_fake_devices: bool = False,
        connect_timeout: float = 10,
        backoff_initial: float = 2,
        backoff_max: float = 60,
        metrics_command_timeout: float = 5,
        metrics_cycle_timeout: float = 20,
        metrics_parallel_devices: int = 4,
        capability_refresh_seconds: float = 300,
    ) -> None:
        self.adb = adb
        self.registry = registry
        self.history = history
        self.pipeline = MetricPipeline(
            command_timeout=metrics_command_timeout, cycle_timeout=metrics_cycle_timeout
        )
        self._history_write_healthy = True
        self._history_prune_healthy = True
        self.connectivity_healthy = True
        self.metrics_healthy = True
        self._metric_semaphore = asyncio.Semaphore(metrics_parallel_devices)
        self._metric_tasks: dict[str, asyncio.Task[bool | None]] = {}
        self._retired_metric_tasks: set[asyncio.Task[bool | None]] = set()
        self._generation: dict[str, int] = {}
        self._probed_at: dict[str, float] = {}
        self._force_probe: set[str] = set()
        self._capability_refresh = capability_refresh_seconds
        self._closing = False
        self.discovery = DiscoveryService(adb, enable_mdns=enable_mdns)
        self.connections = ConnectionManager(
            adb,
            connect_timeout=connect_timeout,
            backoff_initial=backoff_initial,
            backoff_max=backoff_max,
        )
        self.devices: dict[str, Device] = {}
        self.configs: dict[str, RegisteredDevice] = {}
        self.snapshots: dict[str, MetricSnapshot] = {}
        self.observations: dict[str, ConnectionObservation] = {}
        self.discovery_snapshot = DiscoverySnapshot({})
        self.ready = False
        self._seed_fake = seed_fake_devices
        self._seed_attempted = False
        self._lock = asyncio.Lock()

    async def _poll(self) -> None:
        configs = await self.registry.list()
        try:
            snapshot = await self.discovery.scan()
        except DiscoveryError:
            self.ready = False
            for device_id in tuple(self.devices):
                self._invalidate_metrics(device_id)
            self.snapshots = {}
            self.discovery_snapshot = DiscoverySnapshot({})
            self.configs = {config.id: config for config in configs}
            self.devices = {
                config.id: self._device(
                    config,
                    ConnectionObservation(
                        config.id,
                        DeviceState.ADB_UNAVAILABLE
                        if config.auto_connect
                        else DeviceState.DISCONNECTED,
                        error_code="adb_unavailable",
                        error_message="ADB server or executable is unavailable",
                    ),
                )
                for config in configs
            }
            self.observations = {
                config.id: ConnectionObservation(config.id, self.devices[config.id].state)
                for config in configs
            }
            return
        self.discovery_snapshot = snapshot
        if self._seed_fake and not self._seed_attempted:
            self._seed_attempted = True
            if not configs:
                for serial in snapshot.transports:
                    await self.registry.create(
                        DeviceRegistration(serial, ConnectionType.USB, serial=serial),
                        device_id=serial,
                    )
                configs = await self.registry.list()
        observations = await self.connections.reconcile(
            configs, snapshot.transports, snapshot.services
        )
        devices: dict[str, Device] = {}
        for config in configs:
            observation = observations[config.id]
            previous = self.devices.get(config.id)
            device = self._device(config, observation)
            same_connection = (
                previous is not None
                and previous.state == DeviceState.ONLINE
                and device.state == DeviceState.ONLINE
                and previous.serial == device.serial
            )
            if device.state == DeviceState.ONLINE:
                refresh = (
                    not same_connection
                    or config.id in self._force_probe
                    or monotonic() - self._probed_at.get(config.id, 0) >= self._capability_refresh
                )
                if refresh:
                    self._invalidate_metrics(config.id)
                    await DeviceProbe(self.adb).probe(device)
                    self._probed_at[config.id] = monotonic()
                    self._force_probe.discard(config.id)
                if device.state == DeviceState.ONLINE and not same_connection:
                    await self.registry.mark_connected(config.id, datetime.now(UTC))
                if device.state != DeviceState.ONLINE:
                    self._invalidate_metrics(config.id)
                    observations[config.id] = ConnectionObservation(
                        config.id,
                        DeviceState.ERROR,
                        device.serial,
                        error_code="probe_failed",
                        error_message="Device shell probe failed",
                    )
            else:
                self._invalidate_metrics(config.id)
            devices[config.id] = device
        for missing in self.devices.keys() - devices.keys():
            self._invalidate_metrics(missing)
        self.configs = {config.id: config for config in await self.registry.list()}
        self.devices = devices
        self.observations = observations
        self.ready = True

    def _invalidate_metrics(self, device_id: str) -> None:
        self._generation[device_id] = self._generation.get(device_id, 0) + 1
        self.snapshots.pop(device_id, None)
        self.pipeline.reset(device_id)
        task = self._metric_tasks.pop(device_id, None)
        if task is not None:
            self._retired_metric_tasks.add(task)
            task.add_done_callback(self._retired_metric_tasks.discard)
            task.cancel()

    @property
    def history_healthy(self) -> bool:
        return self._history_write_healthy and self._history_prune_healthy

    async def _collect_device(self, device: Device, generation: int) -> bool | None:
        try:
            async with self._metric_semaphore:
                snapshot = await self.pipeline.collect(device, self.adb)
                async with self._lock:
                    current = self.devices.get(device.id)
                    if (
                        self._closing
                        or self._generation.get(device.id, 0) != generation
                        or current is None
                        or current.state != DeviceState.ONLINE
                        or current.serial != device.serial
                    ):
                        return None
                    current.capabilities = set(device.capabilities)
                    self.snapshots[device.id] = snapshot
                # Persistence runs outside the connectivity/configuration lock.
                try:
                    await self.history.append(snapshot)
                except HistoryError:
                    self._history_write_healthy = False
                    return False
                else:
                    return True
        except asyncio.CancelledError:
            raise
        except Exception:
            # An isolated collector failure must not stop fleet connectivity or peers.
            if self._generation.get(device.id, 0) == generation:
                self.snapshots.pop(device.id, None)
        finally:
            if self._metric_tasks.get(device.id) is asyncio.current_task():
                self._metric_tasks.pop(device.id, None)
        return None

    async def collect_metrics(self) -> None:
        async with self._lock:
            if self._closing:
                return
            tasks: list[asyncio.Task[bool | None]] = []
            for device in self.devices.values():
                if device.state != DeviceState.ONLINE:
                    continue
                task = self._metric_tasks.get(device.id)
                if task is None or task.done():
                    task = asyncio.create_task(
                        self._collect_device(deepcopy(device), self._generation.get(device.id, 0))
                    )
                    self._metric_tasks[device.id] = task
                tasks.append(task)
        if tasks:
            # Jobs belong to the application, not to any one request waiting on
            # them. Cancelling a waiter must not cancel a peer's shared collection.
            # stop_metrics() retains ownership and drains every active/retired job.
            results = await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
            # A successful peer cannot mask another device's failed persistence.
            # Cancelled/invalidated batches cannot establish storage recovery.
            if any(result is False for result in results):
                self._history_write_healthy = False
            elif all(result is True for result in results):
                self._history_write_healthy = True

    async def run_metrics(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)  # noqa: ASYNC110 - scheduled sampling
            await self.collect_metrics()
            try:
                await self.history.prune()
            except HistoryError:
                self._history_prune_healthy = False
            else:
                self._history_prune_healthy = True

    async def stop_metrics(self) -> None:
        self._closing = True
        tasks = (*self._metric_tasks.values(), *self._retired_metric_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._metric_tasks.clear()
        self._retired_metric_tasks.clear()

    def _device(self, config: RegisteredDevice, observation: ConnectionObservation) -> Device:
        previous = self.devices.get(config.id)
        serial = observation.serial or config.serial or config.address or ""
        if (
            previous is not None
            and previous.state == DeviceState.ONLINE
            and observation.state == DeviceState.ONLINE
            and previous.serial == serial
        ):
            device = deepcopy(previous)
            device.name = config.name
            device.last_seen = datetime.now(UTC)
            return device
        return Device(
            id=config.id,
            serial=serial,
            name=config.name,
            state=observation.state,
            connection_type=config.connection_type,
            last_seen=previous.last_seen if previous else config.last_connected_at,
        )

    async def poll(self, *, collect: bool = True) -> None:
        async with self._lock:
            try:
                await self._poll()
            except Exception:
                self.ready = False
                self.snapshots = {}
                raise
        if collect:
            await self.collect_metrics()

    async def run(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)  # noqa: ASYNC110 - scheduled polling
            await self.poll(collect=False)

    def observation_generation(self, device_id: str) -> int:
        """Observation epoch changes whenever reconnect invalidates collected data."""
        return self._generation.get(device_id, 0)

    def get(self, device_id: str) -> Device:
        try:
            return self.devices[device_id]
        except KeyError as error:
            raise DeviceNotFound("Device not found") from error

    def discovered(self) -> list[DiscoveredDevice]:
        return discovered_devices(
            self.discovery_snapshot, list(self.configs.values()), self.observations
        )

    async def register(self, registration: DeviceRegistration) -> Device:
        async with self._lock:
            config = await self.registry.create(registration)
            await self._poll()
            result = self.get(config.id)
        await self.collect_metrics()
        return result

    async def update(self, device_id: str, registration: DeviceRegistration) -> Device:
        return await self.patch(device_id, lambda current: registration)

    async def patch(
        self, device_id: str, transform: Callable[[RegisteredDevice], DeviceRegistration]
    ) -> Device:
        async with self._lock:
            old = await self.registry.get(device_id)
            config = await self.registry.update(device_id, transform(old))
            changed = (old.host, old.port, old.serial, old.mdns_service, old.connection_type) != (
                config.host,
                config.port,
                config.serial,
                config.mdns_service,
                config.connection_type,
            )
            if changed or not config.auto_connect:
                self._invalidate_metrics(device_id)
                self._probed_at.pop(device_id, None)
                await self.connections.disconnect(old)
                await self.connections.forget(device_id)
            await self._poll()
            result = self.get(device_id)
        await self.collect_metrics()
        return result

    async def switch_to_tcp(self, device_id: str) -> Device:
        """Move an authorized wireless transport to TCP, retaining its registry identity."""
        async with self._lock:
            config = await self.registry.get(device_id)
            device = self.get(device_id)
            if config.connection_type != ConnectionType.WIRELESS_ADB or config.host is None:
                raise DeviceUnavailable("A registered Wireless Debugging device is required")
            if (
                device.state != DeviceState.ONLINE
                or DeviceCapability.ADB_SHELL not in device.capabilities
            ):
                raise DeviceUnavailable("Connect and authorize the wireless device first")
            address = f"[{config.host}]:5555" if ":" in config.host else f"{config.host}:5555"
            if any(c.id != device_id and c.address == address for c in await self.registry.list()):
                raise DeviceUnavailable(
                    "Port 5555 is already registered; remove the duplicate first"
                )
            invalidated = False
            try:
                async with asyncio.timeout(20):
                    if (await self.adb.list_devices()).get(device.serial) != DeviceState.ONLINE:
                        raise DeviceUnavailable("Device is offline or unauthorized")
                    source = await self.adb.shell(device.serial, ("getprop",), timeout=5)
                    properties = parse_getprop(source.stdout)
                    identity = properties.get("ro.serialno") or properties.get("ro.boot.serialno")
                    if source.timeout or source.exit_code != 0 or not identity:
                        raise DeviceUnavailable(
                            "Cannot verify device identity; TCP mode was not changed"
                        )
                    registered_identity = config.metadata.get("wireless_identity")
                    if registered_identity and registered_identity != identity:
                        raise DeviceUnavailable(
                            "Wireless device identity changed; TCP mode was not changed"
                        )
                    self._invalidate_metrics(device_id)
                    self._probed_at.pop(device_id, None)
                    pending = ConnectionObservation(device_id, DeviceState.CONNECTING)
                    self.devices[device_id] = self._device(config, pending)
                    self.observations[device_id] = pending
                    invalidated = True
                    result = await self.adb.enable_tcp(device.serial, timeout=5)
                    if result.timeout:
                        raise TimeoutError
                    if result.exit_code != 0:
                        raise DeviceUnavailable("Device could not enable ADB TCP mode")
                    for attempt in range(5):
                        if attempt:
                            await asyncio.sleep(0.5)
                        await self.adb.connect(address)
                        if (await self.adb.list_devices()).get(address) == DeviceState.ONLINE:
                            break
                    else:
                        raise DeviceUnavailable(
                            "TCP port 5555 is not authorized or reachable. "
                            "Registration is unchanged; reconnect Wireless Debugging to retry."
                        )
                    target = await self.adb.shell(address, ("getprop",), timeout=5)
                    target_properties = parse_getprop(target.stdout)
                    target_identity = target_properties.get("ro.serialno") or target_properties.get(
                        "ro.boot.serialno"
                    )
                    if target.timeout or target.exit_code != 0 or target_identity != identity:
                        await self.adb.disconnect(address)
                        raise DeviceUnavailable(
                            "TCP device identity did not match; registration unchanged"
                        )
            except TimeoutError as exc:
                raise DeviceUnavailable(
                    "TCP switch timed out; reconnect Wireless Debugging before retrying"
                ) from exc
            except (OSError, RuntimeError) as exc:
                if isinstance(exc, DeviceUnavailable):
                    raise
                raise DeviceUnavailable(
                    "ADB transport failed; reconnect Wireless Debugging before retrying"
                ) from exc
            finally:
                if invalidated:
                    await self.connections.forget(device_id)
                    stale = ConnectionObservation(device_id, DeviceState.OFFLINE)
                    self.observations[device_id] = stale
                    self.devices[device_id] = self._device(config, stale)
            await self.registry.update(
                device_id,
                DeviceRegistration(
                    name=config.name,
                    connection_type=ConnectionType.ADB_TCP,
                    host=config.host,
                    port=5555,
                    metadata=config.metadata,
                    auto_connect=True,
                ),
            )
            await self.adb.disconnect(device.serial)
            # adbd can briefly reject a shell after reporting the TCP transport online.
            # Wait for the full capability probe, rather than returning a successful
            # switch with probe_failed and leaving the next scheduled poll to recover.
            try:
                async with asyncio.timeout(15):
                    for attempt in range(3):
                        if attempt:
                            await asyncio.sleep(0.5)
                        await self._poll()
                        if self.get(device_id).state == DeviceState.ONLINE:
                            break
                    else:
                        raise DeviceUnavailable(
                            "ADB TCP is enabled on port 5555, but the shell is not ready. "
                            "Click Reconnect to retry; pairing again is not required."
                        )
            except TimeoutError as exc:
                self._invalidate_metrics(device_id)
                pending = ConnectionObservation(device_id, DeviceState.RECONNECTING)
                self.observations[device_id] = pending
                self.devices[device_id] = self._device(await self.registry.get(device_id), pending)
                raise DeviceUnavailable(
                    "ADB TCP is enabled on port 5555; shell verification timed out. "
                    "Click Reconnect to retry."
                ) from exc
            result_device = self.get(device_id)
        await self.collect_metrics()
        return result_device

    async def remove(self, device_id: str) -> None:
        async with self._lock:
            config = await self.registry.get(device_id)
            # Persist disabled intent before touching the transport.
            await self.registry.set_auto_connect(device_id, False)
            self._invalidate_metrics(device_id)
            await self.connections.disconnect(config)
            await self.registry.delete(device_id)
            await self.connections.forget(device_id)
            self.configs.pop(device_id, None)
            self.devices.pop(device_id, None)
            self.snapshots.pop(device_id, None)
            self.observations.pop(device_id, None)

    async def connect(self, device_id: str) -> Device:
        async with self._lock:
            config = await self.registry.set_auto_connect(device_id, True)
            pending = ConnectionObservation(device_id, DeviceState.CONNECTING)
            self.devices[device_id] = self._device(config, pending)
            self.observations[device_id] = pending
            self._invalidate_metrics(device_id)
            await self.connections.connect(config)
            await self._poll()
            result = self.get(device_id)
        await self.collect_metrics()
        return result

    async def disconnect(self, device_id: str) -> Device:
        async with self._lock:
            config = await self.registry.set_auto_connect(device_id, False)
            self._invalidate_metrics(device_id)
            observation = await self.connections.disconnect(config)
            disabled = ConnectionObservation(
                device_id,
                DeviceState.DISCONNECTED,
                error_code=observation.error_code,
                error_message=observation.error_message,
            )
            self.configs[device_id] = config
            self.observations[device_id] = disabled
            self.snapshots.pop(device_id, None)
            self.devices[device_id] = self._device(config, disabled)
            return self.devices[device_id]

    async def refresh_capabilities(self, device_id: str) -> Device:
        async with self._lock:
            await self.registry.get(device_id)
            self._force_probe.add(device_id)
            await self._poll()
            device = self.get(device_id)
            if device.state != DeviceState.ONLINE:
                raise DeviceUnavailable("Device is not online and authorized")
            result = device
        await self.collect_metrics()
        return result
