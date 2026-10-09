"""Reconcile registry intent with authenticated ADB transport observations."""

import asyncio
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from android_fleet.adb.base import AdbClient
from android_fleet.adb.connection_models import ConnectionObservation
from android_fleet.devices.models import ConnectionType, DeviceState
from android_fleet.devices.registry_models import RegisteredDevice
from android_fleet.discovery.models import MdnsService


@dataclass
class _Runtime:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    endpoint: str | None = None
    fingerprint: tuple[object, ...] | None = None
    attempts: int = 0
    retry_at: float = 0
    observation: ConnectionObservation | None = None


class ConnectionManager:
    def __init__(
        self,
        adb: AdbClient,
        *,
        connect_timeout: float = 10,
        backoff_initial: float = 2,
        backoff_max: float = 60,
        clock: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if connect_timeout <= 0 or backoff_initial <= 0 or backoff_max < backoff_initial:
            raise ValueError("timeouts and backoff must be positive and ordered")
        self._adb = adb
        self._timeout = connect_timeout
        self._initial = backoff_initial
        self._maximum = backoff_max
        self._clock = clock
        self._random = random_value
        self._runtime: dict[str, _Runtime] = {}
        self._services: tuple[MdnsService, ...] = ()

    def _entry(self, device_id: str) -> _Runtime:
        return self._runtime.setdefault(device_id, _Runtime())

    @staticmethod
    def _fingerprint(config: RegisteredDevice) -> tuple[object, ...]:
        return (
            config.connection_type,
            config.host,
            config.port,
            config.serial,
            config.mdns_service,
        )

    def _endpoint(self, config: RegisteredDevice, runtime: _Runtime | None = None) -> str | None:
        if config.connection_type == ConnectionType.USB:
            return None
        if config.mdns_service:
            discovered = next(
                (
                    service.address
                    for service in self._services
                    if service.name == config.mdns_service
                    and service.service_type == "_adb-tls-connect._tcp"
                ),
                None,
            )
            if discovered:
                return discovered
            if runtime and runtime.fingerprint == self._fingerprint(config) and runtime.endpoint:
                return runtime.endpoint
        return config.address

    def _pairing_advertised(self, config: RegisteredDevice) -> bool:
        if not config.mdns_service:
            return False
        pairing_name = (
            config.mdns_service.removesuffix("._adb-tls-connect._tcp") + "._adb-tls-pairing._tcp"
        )
        return any(
            service.name == pairing_name and service.service_type == "_adb-tls-pairing._tcp"
            for service in self._services
        )

    @staticmethod
    def _transport(
        config: RegisteredDevice, endpoint: str | None, transports: dict[str, DeviceState]
    ) -> tuple[str | None, DeviceState | None]:
        candidates = (
            (config.serial,)
            if config.connection_type == ConnectionType.USB
            else (endpoint, config.serial, config.mdns_service)
        )
        for candidate in candidates:
            if candidate is not None and candidate in transports:
                return candidate, transports[candidate]
        return None, None

    def _observe(
        self,
        config: RegisteredDevice,
        runtime: _Runtime,
        state: DeviceState,
        *,
        serial: str | None = None,
        code: str | None = None,
    ) -> ConnectionObservation:
        messages = {
            "adb_unavailable": "ADB server or executable is unavailable",
            "connection_timeout": "ADB connection operation timed out",
            "connection_failed": "ADB transport connection failed",
            "connection_refused": "ADB connection refused; verify the ADB port and firewall rules",
            "host_unreachable": "Device host unreachable; verify the address and routing",
            "host_resolution_failed": "Device hostname unresolved; verify DNS and the address",
            "authorization_required": "Authorize this management host on the device",
            "pairing_required": "Pair this management host using Android Wireless Debugging",
            "disconnect_failed": "ADB transport disconnect failed",
        }
        retry = max(0.0, runtime.retry_at - self._clock())
        observation = ConnectionObservation(
            device_id=config.id,
            state=state,
            serial=serial,
            error_code=code,
            error_message=messages.get(code) if code else None,
            retry_in_seconds=retry if retry > 0 else None,
        )
        runtime.observation = observation
        return observation

    def _backoff(self, runtime: _Runtime, *, unauthorized: bool = False) -> None:
        base = min(self._maximum, self._initial * 2 ** min(runtime.attempts, 30))
        runtime.attempts = max(1, runtime.attempts) if unauthorized else runtime.attempts + 1
        jitter = 0.5 + 0.5 * min(1.0, max(0.0, self._random()))
        runtime.retry_at = self._clock() + (self._maximum if unauthorized else base * jitter)

    @staticmethod
    def _failure_code(output: str) -> str:
        reported = output.lower()
        categories = (
            (
                "pairing_required",
                ("pairing required", "failed to authenticate", "authentication failed"),
            ),
            ("connection_refused", ("connection refused", "actively refused")),
            (
                "host_unreachable",
                (
                    "no route to host",
                    "network is unreachable",
                    "host is unreachable",
                    "host unreachable",
                ),
            ),
            (
                "host_resolution_failed",
                (
                    "failed to resolve",
                    "cannot resolve",
                    "could not resolve",
                    "name or service not known",
                    "nodename nor servname",
                    "no such host",
                    "temporary failure in name resolution",
                ),
            ),
            ("connection_timeout", ("connection timed out", "operation timed out")),
        )
        for code, markers in categories:
            if any(marker in reported for marker in markers):
                return code
        return "connection_failed"

    async def _prepare(self, config: RegisteredDevice, runtime: _Runtime) -> bool:
        fingerprint = self._fingerprint(config)
        endpoint = self._endpoint(config, runtime)
        changed = runtime.fingerprint is not None and (
            fingerprint != runtime.fingerprint or endpoint != runtime.endpoint
        )
        if changed and runtime.endpoint:
            result = await asyncio.wait_for(self._adb.disconnect(runtime.endpoint), self._timeout)
            if result.timeout or result.exit_code != 0:
                raise RuntimeError("disconnect failed")
        if changed:
            runtime.attempts = 0
            runtime.retry_at = 0
            runtime.observation = None
        runtime.fingerprint = fingerprint
        runtime.endpoint = endpoint
        return changed

    async def _attempt(
        self,
        config: RegisteredDevice,
        runtime: _Runtime,
    ) -> ConnectionObservation:
        if runtime.endpoint is None:
            missing_state = (
                DeviceState.PAIRING_REQUIRED
                if self._pairing_advertised(config)
                else DeviceState.OFFLINE
            )
            return self._observe(
                config,
                runtime,
                missing_state,
                code="pairing_required" if missing_state == DeviceState.PAIRING_REQUIRED else None,
            )
        self._observe(
            config,
            runtime,
            DeviceState.RECONNECTING if runtime.attempts else DeviceState.CONNECTING,
        )
        try:
            async with asyncio.timeout(self._timeout):
                existing = await self._adb.list_devices()
                serial, state = self._transport(config, runtime.endpoint, existing)
                if state in (DeviceState.ONLINE, DeviceState.UNAUTHORIZED):
                    if state == DeviceState.ONLINE:
                        runtime.attempts = 0
                        runtime.retry_at = 0
                    else:
                        self._backoff(runtime, unauthorized=True)
                    return self._observe(
                        config,
                        runtime,
                        state,
                        serial=serial,
                        code="authorization_required"
                        if state == DeviceState.UNAUTHORIZED
                        else None,
                    )
                result = await self._adb.connect(runtime.endpoint)
                if result.timeout:
                    raise TimeoutError
                # ADB can return success status while reporting a rejected connection.
                # Only an authorized entry from devices can establish ONLINE state.
                transports = await self._adb.list_devices()
        except FileNotFoundError:
            self._backoff(runtime)
            return self._observe(
                config, runtime, DeviceState.ADB_UNAVAILABLE, code="adb_unavailable"
            )
        except TimeoutError:
            self._backoff(runtime)
            return self._observe(config, runtime, DeviceState.ERROR, code="connection_timeout")
        except (OSError, RuntimeError):
            self._backoff(runtime)
            return self._observe(config, runtime, DeviceState.ERROR, code="connection_failed")
        serial, state = self._transport(config, runtime.endpoint, transports)
        if state == DeviceState.ONLINE:
            runtime.attempts = 0
            runtime.retry_at = 0
            return self._observe(config, runtime, state, serial=serial)
        failure_code = self._failure_code(result.stdout + " " + result.stderr)
        if state in (None, DeviceState.OFFLINE) and failure_code == "pairing_required":
            state = DeviceState.PAIRING_REQUIRED
        self._backoff(
            runtime, unauthorized=state in (DeviceState.UNAUTHORIZED, DeviceState.PAIRING_REQUIRED)
        )
        return self._observe(
            config,
            runtime,
            state or DeviceState.OFFLINE,
            serial=serial,
            code="authorization_required"
            if state == DeviceState.UNAUTHORIZED
            else "pairing_required"
            if state == DeviceState.PAIRING_REQUIRED
            else failure_code,
        )

    async def reconcile(
        self,
        configs: Sequence[RegisteredDevice],
        transports: dict[str, DeviceState],
        services: Sequence[MdnsService] = (),
    ) -> dict[str, ConnectionObservation]:
        self._services = tuple(services)
        observations: dict[str, ConnectionObservation] = {}
        for config in configs:
            runtime = self._entry(config.id)
            async with runtime.lock:
                if not config.auto_connect:
                    observations[config.id] = self._observe(
                        config, runtime, DeviceState.DISCONNECTED
                    )
                    continue
                try:
                    changed = await self._prepare(config, runtime)
                    observed_transports = (
                        await asyncio.wait_for(self._adb.list_devices(), self._timeout)
                        if changed
                        else transports
                    )
                except FileNotFoundError:
                    self._backoff(runtime)
                    observations[config.id] = self._observe(
                        config, runtime, DeviceState.ADB_UNAVAILABLE, code="adb_unavailable"
                    )
                    continue
                except (OSError, RuntimeError, TimeoutError):
                    observations[config.id] = self._observe(
                        config, runtime, DeviceState.ERROR, code="disconnect_failed"
                    )
                    continue
                serial, state = self._transport(config, runtime.endpoint, observed_transports)
                if state in (DeviceState.ONLINE, DeviceState.UNAUTHORIZED):
                    if state == DeviceState.ONLINE:
                        runtime.retry_at = 0
                        runtime.attempts = 0
                    else:
                        self._backoff(runtime, unauthorized=True)
                    observations[config.id] = self._observe(
                        config,
                        runtime,
                        state,
                        serial=serial,
                        code="authorization_required"
                        if state == DeviceState.UNAUTHORIZED
                        else None,
                    )
                elif config.connection_type == ConnectionType.USB:
                    observations[config.id] = self._observe(
                        config, runtime, state or DeviceState.OFFLINE, serial=serial
                    )
                elif runtime.retry_at > self._clock():
                    previous = runtime.observation
                    observations[config.id] = self._observe(
                        config,
                        runtime,
                        DeviceState.RECONNECTING,
                        code=previous.error_code if previous else None,
                    )
                else:
                    observations[config.id] = await self._attempt(config, runtime)
        return observations

    async def connect(self, config: RegisteredDevice) -> ConnectionObservation:
        runtime = self._entry(config.id)
        async with runtime.lock:
            try:
                await self._prepare(config, runtime)
                async with asyncio.timeout(self._timeout):
                    transports = await self._adb.list_devices()
            except FileNotFoundError:
                return self._observe(
                    config, runtime, DeviceState.ADB_UNAVAILABLE, code="adb_unavailable"
                )
            except TimeoutError:
                return self._observe(config, runtime, DeviceState.ERROR, code="connection_timeout")
            except (OSError, RuntimeError):
                return self._observe(config, runtime, DeviceState.ERROR, code="connection_failed")
            serial, state = self._transport(config, runtime.endpoint, transports)
            runtime.attempts = 0
            runtime.retry_at = 0
            if state in (DeviceState.ONLINE, DeviceState.UNAUTHORIZED):
                return self._observe(
                    config,
                    runtime,
                    state,
                    serial=serial,
                    code="authorization_required" if state == DeviceState.UNAUTHORIZED else None,
                )
            return await self._attempt(config, runtime)

    async def disconnect(self, config: RegisteredDevice) -> ConnectionObservation:
        runtime = self._entry(config.id)
        async with runtime.lock:
            endpoint = runtime.endpoint or self._endpoint(config)
            if endpoint:
                try:
                    result = await asyncio.wait_for(self._adb.disconnect(endpoint), self._timeout)
                    if result.timeout or result.exit_code != 0:
                        raise RuntimeError("disconnect failed")
                except (OSError, RuntimeError, TimeoutError):
                    return self._observe(
                        config, runtime, DeviceState.ERROR, code="disconnect_failed"
                    )
            runtime.retry_at = 0
            runtime.attempts = 0
            return self._observe(config, runtime, DeviceState.DISCONNECTED)

    async def forget(self, device_id: str) -> None:
        runtime = self._runtime.get(device_id)
        if runtime:
            async with runtime.lock:
                self._runtime.pop(device_id, None)
