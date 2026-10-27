"""Read-only monitoring and narrowly scoped M1 connectivity controls."""

import asyncio
import re
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.routing import Match

from android_fleet.adb.base import AdbClient
from android_fleet.adb.fake import FakeAdbClient
from android_fleet.adb.pairing import PairingService
from android_fleet.adb.subprocess import SubprocessAdbClient
from android_fleet.alerts.api import router as alert_router
from android_fleet.alerts.engine import AlertEngine
from android_fleet.alerts.store import AlertError, AlertNotFound, AlertStore
from android_fleet.api.metric_models import (
    CurrentMetricsResponse,
    HistoryResponse,
    current_response,
    history_response,
)
from android_fleet.api.models import DevicePatch, DeviceRequest, DeviceResponse
from android_fleet.api.security import ControlDenied
from android_fleet.api.settings import settings_router
from android_fleet.control.api import router as control_router
from android_fleet.control.manager import PERMISSIONS, Manager
from android_fleet.core.runtime_settings import RuntimeSettings
from android_fleet.core.settings import Settings
from android_fleet.devices.models import Device, DeviceState
from android_fleet.devices.registry import (
    DeviceNotFound,
    DuplicateDevice,
    InvalidRegistration,
    RegistryError,
    SQLiteDeviceRegistry,
)
from android_fleet.devices.registry_models import DeviceRegistration, RegisteredDevice
from android_fleet.devices.service import DeviceUnavailable, FleetService
from android_fleet.metrics.exporter import render_metrics
from android_fleet.metrics.history import HistoryError, InvalidHistoryQuery, MetricHistoryStore
from android_fleet.screen.api import router as screen_router
from android_fleet.screen.manager import ScreenManager
from android_fleet.screen.metrics import render_screen_metrics
from android_fleet.security import SecurityService
from android_fleet.setup.service import DeviceSetup
from android_fleet.terminal.api import router as terminal_router
from android_fleet.terminal.manager import TerminalManager
from android_fleet.terminal.metrics import render as render_terminal_metrics
from android_fleet.terminal.profiles import ProfileService
from android_fleet.terminal.ssh import SSHGateway


def create_app(
    adb: AdbClient | None = None,
    settings: Settings | None = None,
    registry: SQLiteDeviceRegistry | None = None,
    history: MetricHistoryStore | None = None,
) -> FastAPI:
    configuration = settings or Settings()
    client: AdbClient = (
        adb
        if adb is not None
        else (
            FakeAdbClient()
            if configuration.fake_adb
            else SubprocessAdbClient(
                executable=configuration.adb_binary,
                server_host=configuration.adb_server_host,
                server_port=configuration.adb_server_port,
                timeout=configuration.connect_timeout,
            )
        )
    )
    storage = (
        registry if registry is not None else SQLiteDeviceRegistry(configuration.registry_path)
    )
    metric_history = (
        history
        if history is not None
        else MetricHistoryStore(
            configuration.history_path,
            retention_seconds=configuration.history_retention_seconds,
            max_points=configuration.history_max_points,
        )
    )
    service = FleetService(
        client,
        storage,
        metric_history,
        enable_mdns=configuration.enable_mdns,
        seed_fake_devices=configuration.seed_fake_devices and isinstance(client, FakeAdbClient),
        connect_timeout=configuration.connect_timeout,
        backoff_initial=configuration.backoff_initial,
        backoff_max=configuration.backoff_max,
        metrics_command_timeout=configuration.metrics_command_timeout,
        metrics_cycle_timeout=configuration.metrics_cycle_timeout,
        metrics_parallel_devices=configuration.metrics_parallel_devices,
        capability_refresh_seconds=configuration.capability_refresh_seconds,
    )

    alert_path = configuration.alerts_path or (
        ":memory:"
        if str(configuration.registry_path) == ":memory:"
        else Path(configuration.registry_path).parent / "alerts.sqlite3"
    )
    transient = (
        tempfile.TemporaryDirectory(prefix="android-fleet-")
        if str(configuration.registry_path) == ":memory:"
        else None
    )
    state_directory = (
        Path(transient.name) if transient else Path(configuration.registry_path).parent
    )
    security = SecurityService(configuration, state_directory / "security.sqlite3")
    screens = ScreenManager(client, service, security, configuration)
    profiles = ProfileService(
        state_directory / "ssh.sqlite3",
        configuration.ssh_encryption_key.get_secret_value()
        if configuration.ssh_encryption_key
        else None,
        configuration.ssh_destinations,
    )
    gateway = SSHGateway(profiles)
    terminals = TerminalManager(
        configuration.model_copy(
            update={
                "terminal_path": configuration.terminal_path
                or state_directory / "terminals.sqlite3"
            }
        ),
        service,
        security,
        gateway,
    )
    pairing = PairingService(
        client, service, security, configuration, state_directory / "pairing.sqlite3"
    )
    runtime = RuntimeSettings(
        {
            "metrics_interval_seconds": configuration.metrics_interval_seconds,
            "poll_interval_seconds": configuration.poll_interval_seconds,
            "alerts_interval_seconds": configuration.alerts_interval_seconds,
        },
        state_directory / "settings.sqlite3",
    )
    service.metrics_interval_for = lambda device_id: runtime.device_value(
        device_id, "metrics_interval_seconds"
    )
    operations = Manager(
        client,
        service,
        configuration,
        Path(configuration.operations_path)
        if configuration.operations_path
        else state_directory / "operations.sqlite3",
        setup=DeviceSetup(client, service, profiles, state_directory / "control-artifacts"),
    )
    alert_store = AlertStore(alert_path)
    alert_engine = AlertEngine(
        alert_store,
        service,
        max_age_seconds=configuration.metrics_max_age_seconds,
        retention_seconds=configuration.alerts_retention_seconds,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        worker: asyncio.Task[None] | None = None
        metrics_worker: asyncio.Task[None] | None = None
        alerts_worker: asyncio.Task[None] | None = None
        security_worker: asyncio.Task[None] | None = None
        try:
            await security.initialize()
            await pairing.initialize()
            await profiles.initialize()
            await terminals.initialize()

            async def maintain_security() -> None:
                while True:
                    await asyncio.sleep(60)
                    await security.cleanup()

            security_worker = asyncio.create_task(maintain_security())
            await storage.initialize()
            await runtime.initialize()
            await metric_history.initialize()
            # Initial batch keeps existing M0/M1 startup semantics; later sampling
            # has its own worker and never holds the connection orchestration lock.
            await service.poll()
            await screens.start()
            await operations.initialize()
            await operations.start()
            await alert_engine.initialize()
            await alert_engine.evaluate()
            alerts_worker = asyncio.create_task(
                alert_engine.run(lambda: runtime.value("alerts_interval_seconds"))
            )
            worker = asyncio.create_task(
                service.run(lambda: runtime.value("poll_interval_seconds"))
            )
            metrics_worker = asyncio.create_task(
                service.run_metrics(lambda: runtime.value("metrics_interval_seconds"))
            )
            application.state.worker = worker
            application.state.metrics_worker = metrics_worker

            def worker_finished(task: asyncio.Task[None]) -> None:
                service.connectivity_healthy = False
                if not task.cancelled() and task.exception() is not None:
                    service.ready = False
                    service.snapshots = {}
                    for device in service.devices.values():
                        device.state = DeviceState.ERROR
                        device.capabilities.clear()
                        device.root_available = None

            def metrics_finished(task: asyncio.Task[None]) -> None:
                service.metrics_healthy = False
                if not task.cancelled() and task.exception() is not None:
                    service.metrics_healthy = False
                    service.snapshots = {}

            worker.add_done_callback(worker_finished)
            metrics_worker.add_done_callback(metrics_finished)

            def alerts_finished(task: asyncio.Task[None]) -> None:
                alert_engine.healthy = False

            alerts_worker.add_done_callback(alerts_finished)
            yield
        finally:
            service.ready = False
            for task in (worker, metrics_worker, alerts_worker, security_worker):
                if task is not None:
                    task.cancel()
            try:
                tasks = [
                    task
                    for task in (worker, metrics_worker, alerts_worker, security_worker)
                    if task is not None
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await service.stop_metrics()
            finally:
                try:
                    await operations.close()
                    await terminals.close()
                    await screens.close()
                    await alert_store.close()
                    await metric_history.close()
                finally:
                    await storage.close()
                    await security.close()
                    if transient:
                        transient.cleanup()

    application = FastAPI(title="Android Fleet Manager", version="0.4.0", lifespan=lifespan)
    application.state.fleet = service
    application.state.registry = storage
    application.state.history = metric_history
    application.state.alerts = alert_engine
    application.state.security = security
    application.state.operations = operations
    application.state.screens = screens
    application.state.terminals = terminals
    application.state.ssh_profiles = profiles
    application.state.pairing = pairing
    application.state.runtime_settings = runtime

    def error_response(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(error.status_code, "request_failed", str(error.detail))

    @application.exception_handler(AlertNotFound)
    async def alert_not_found(request: Request, error: AlertNotFound) -> JSONResponse:
        return error_response(404, "alert_not_found", str(error))

    @application.exception_handler(AlertError)
    async def alerts_unavailable(request: Request, error: AlertError) -> JSONResponse:
        return error_response(503, "alerts_unavailable", "Alert storage is unavailable")

    @application.exception_handler(DeviceNotFound)
    async def not_found(request: Request, error: DeviceNotFound) -> JSONResponse:
        return error_response(404, "device_not_found", "Device not found")

    @application.exception_handler(DuplicateDevice)
    async def duplicate(request: Request, error: DuplicateDevice) -> JSONResponse:
        return error_response(409, "duplicate_device", "A matching device is already registered")

    @application.exception_handler(InvalidRegistration)
    async def invalid(request: Request, error: InvalidRegistration) -> JSONResponse:
        return error_response(422, "invalid_registration", str(error))

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        path = request.url.path
        if (
            path.startswith("/api/v1/pairing/")
            or re.fullmatch(r"/api/v1/devices/[^/]+/wireless-port", path)
            or path.startswith("/api/v1/terminal/")
            or path.startswith("/api/v1/ssh/")
        ):
            permission = "security.manage"
            if path.startswith("/api/v1/ssh/"):
                permission = "terminal:profile:manage"
            elif path.startswith("/api/v1/terminal/"):
                body = error.body if isinstance(error.body, dict) else {}
                connection_type = body.get("connection_type")
                permission = (
                    "terminal:" + connection_type
                    if isinstance(connection_type, str) and connection_type in {"adb", "ssh"}
                    else "terminal:view"
                )
            try:
                actor = await security.authorize(request, permission)
            except HTTPException as denial:
                return error_response(denial.status_code, "control_denied", "Permission denied")
            await security.audit(
                actor,
                request.path_params.get("device_id"),
                permission,
                request.state.request_id,
                "allowed",
                "rejected",
                error="invalid_request",
            )
        if request.url.path.startswith("/api/v1/screen/sessions") or re.fullmatch(
            r"/api/v1/devices/[^/]+/screen/sessions", request.url.path
        ):
            try:
                actor = await security.authorize(request, "screen:view")
            except HTTPException as denial:
                return error_response(denial.status_code, "screen_denied", "Permission denied")
            await security.audit(
                actor,
                request.path_params.get("device_id"),
                "screen.session.request",
                request.state.request_id,
                "allowed",
                "rejected",
                error="invalid_request",
            )
        if request.method == "POST" and request.url.path.endswith("/operations"):
            body = error.body if isinstance(error.body, dict) else {}
            action = body.get("action")
            permission = (
                PERMISSIONS.get(action, "control.unknown")
                if isinstance(action, str)
                else "control.unknown"
            )
            request.state.audit_action = (
                action if isinstance(action, str) and action in PERMISSIONS else "control.unknown"
            )
            try:
                actor = await security.authorize(request, permission)
            except HTTPException as denial:
                return error_response(denial.status_code, "control_denied", "Permission denied")
            await security.audit(
                actor,
                request.path_params.get("device_id"),
                action if isinstance(action, str) and action in PERMISSIONS else "control.unknown",
                request.state.request_id,
                "allowed",
                "rejected",
                error="invalid_request",
            )
        issues: list[str] = []
        for issue in error.errors():
            location = ".".join(str(part) for part in issue.get("loc", ()) if part != "body")
            message = issue.get("msg")
            if location and isinstance(message, str):
                issues.append(f"{location}: {message.removeprefix('Value error, ')}")
        detail = f" ({'; '.join(issues)})" if issues else ""
        return error_response(422, "invalid_request", f"Request fields are invalid{detail}")

    @application.exception_handler(RegistryError)
    async def registry_unavailable(request: Request, error: RegistryError) -> JSONResponse:
        return error_response(503, "registry_unavailable", "Device registry is unavailable")

    @application.exception_handler(InvalidHistoryQuery)
    async def invalid_history(request: Request, error: InvalidHistoryQuery) -> JSONResponse:
        return error_response(422, "invalid_history_query", str(error))

    @application.exception_handler(HistoryError)
    async def history_unavailable(request: Request, error: HistoryError) -> JSONResponse:
        return error_response(503, "history_unavailable", "Metric history is unavailable")

    @application.exception_handler(ControlDenied)
    async def control_denied(request: Request, error: ControlDenied) -> JSONResponse:
        return error_response(403, "control_denied", str(error))

    @application.exception_handler(DeviceUnavailable)
    async def device_unavailable(request: Request, error: DeviceUnavailable) -> JSONResponse:
        return error_response(409, "device_unavailable", str(error))

    async def control(request: Request) -> None:
        # The middleware enforces and audits legacy endpoints.
        await security.authorize(
            request,
            "alerts.manage" if request.url.path.startswith("/api/v1/alerts") else "device.manage",
        )

    application.include_router(alert_router(alert_engine, control))
    application.include_router(security.router())
    application.include_router(control_router(operations, security))
    application.include_router(screen_router(screens, security))
    application.include_router(terminal_router(terminals, security))
    application.include_router(profiles.router(security))
    application.include_router(pairing.router())
    application.include_router(settings_router(runtime, service, security))

    @application.middleware("http")
    async def protected_api(request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # Only these complete control routes own their authorization. Device IDs
        # containing route words must never bypass the legacy endpoint guard.
        if (
            not path.startswith("/api/v1/")
            or path == "/api/v1/audit"
            or path.startswith("/api/v1/auth/")
            or path == "/api/v1/operations"
            or path.startswith("/api/v1/operations/")
            or path == "/api/v1/screen/sessions"
            or path.startswith("/api/v1/screen/sessions/")
            or path.startswith("/api/v1/terminal/")
            or path.startswith("/api/v1/ssh/")
            or path.startswith("/api/v1/pairing/")
            or re.fullmatch(r"/api/v1/devices/[^/]+/wireless-port", path)
            or re.fullmatch(r"/api/v1/devices/[^/]+/screen/sessions", path)
            or re.fullmatch(r"/api/v1/devices/[^/]+/(?:operations|apk)", path)
        ):
            return await call_next(request)
        # Unknown URLs keep normal 404/405 behavior; no callable API exists there.
        matched = next(
            (
                route
                for route in application.routes
                if route.matches(request.scope)[0] == Match.FULL
            ),
            None,
        )
        if matched is None:
            return await call_next(request)
        request.state.audit_action = getattr(matched, "name", None) or "protected_request"
        pieces = path.split("/")
        device_id = pieces[4] if len(pieces) > 4 and pieces[3] == "devices" else None
        request.state.audit_device_id = device_id
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
        permission = (
            ("alerts.manage" if path.startswith("/api/v1/alerts") else "device.manage")
            if mutation
            else (
                "alerts.read"
                if path.startswith("/api/v1/alerts")
                else "telemetry.read"
                if "/metrics" in path
                else "device.read"
            )
        )
        started = time.monotonic()
        try:
            actor = await security.authorize(request, permission)
        except HTTPException as error:
            return error_response(error.status_code, "control_denied", "Permission denied")
        try:
            result = await call_next(request)
        except Exception:
            if mutation:
                await security.audit(
                    actor,
                    device_id,
                    request.state.audit_action,
                    request.state.request_id,
                    "allowed",
                    "failed",
                    time.monotonic() - started,
                    "internal_error",
                )
            raise
        if mutation:
            await security.audit(
                actor,
                device_id,
                request.state.audit_action,
                request.state.request_id,
                "allowed",
                "succeeded" if result.status_code < 400 else "failed",
                time.monotonic() - started,
                None if result.status_code < 400 else "request_rejected",
            )
        return result

    def response(device: Device) -> DeviceResponse:
        result = DeviceResponse.model_validate(device)
        config = service.configs[device.id]
        result.host = config.host
        result.port = config.port
        result.mdns_service = config.mdns_service
        result.metadata = dict(config.metadata)
        result.auto_connect = config.auto_connect
        result.created_at = config.created_at
        result.updated_at = config.updated_at
        result.last_connected_at = config.last_connected_at
        observation = service.observations.get(device.id)
        if observation:
            result.error_code = observation.error_code
            result.error_message = observation.error_message
            result.retry_in_seconds = observation.retry_in_seconds
        return result

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    async def ready() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ready"
                if service.ready
                and service.connectivity_healthy
                and service.history_healthy
                and service.metrics_healthy
                and alert_engine.healthy
                else "unavailable"
            },
            status_code=200
            if service.ready
            and service.connectivity_healthy
            and service.history_healthy
            and service.metrics_healthy
            and alert_engine.healthy
            else 503,
        )

    @application.get("/api/v1/devices", response_model=list[DeviceResponse])
    async def devices() -> list[DeviceResponse]:
        return [response(device) for device in service.devices.values()]

    @application.post("/api/v1/devices", status_code=201, dependencies=[Depends(control)])
    async def register_device(body: DeviceRequest) -> DeviceResponse:
        return response(await service.register(body.registration()))

    @application.get("/api/v1/discovery/devices")
    async def discovered() -> dict[str, object]:
        return {
            "devices": [asdict(device) for device in service.discovered()],
            "mdns_enabled": configuration.enable_mdns,
            "mdns_available": service.discovery_snapshot.mdns_available,
        }

    @application.get("/api/v1/devices/{device_id}")
    async def device_details(device_id: str) -> DeviceResponse:
        return response(service.get(device_id))

    @application.patch("/api/v1/devices/{device_id}", dependencies=[Depends(control)])
    async def update_device(device_id: str, body: DevicePatch) -> DeviceResponse:
        def transform(current: RegisteredDevice) -> DeviceRegistration:
            fields = DeviceRequest(
                name=current.name,
                connection_type=current.connection_type,
                host=current.host,
                port=current.port,
                serial=current.serial,
                mdns_service=current.mdns_service,
                metadata=current.metadata,
                auto_connect=current.auto_connect,
            ).model_dump()
            fields.update(body.model_dump(exclude_unset=True))
            try:
                return DeviceRequest.model_validate(fields).registration()
            except ValidationError as error:
                raise InvalidRegistration("Updated configuration fields are invalid") from error

        return response(await service.patch(device_id, transform))

    @application.delete(
        "/api/v1/devices/{device_id}", status_code=204, dependencies=[Depends(control)]
    )
    async def remove_device(device_id: str) -> Response:
        await service.remove(device_id)
        return Response(status_code=204)

    @application.post(
        "/api/v1/devices/{device_id}/connect", status_code=202, dependencies=[Depends(control)]
    )
    async def connect_device(device_id: str) -> DeviceResponse:
        return response(await service.connect(device_id))

    @application.post("/api/v1/devices/{device_id}/disconnect", dependencies=[Depends(control)])
    async def disconnect_device(device_id: str) -> DeviceResponse:
        return response(await service.disconnect(device_id))

    @application.get("/api/v1/devices/{device_id}/capabilities")
    async def capabilities(device_id: str) -> dict[str, object]:
        device = service.get(device_id)
        return {
            "device_id": device_id,
            "state": device.state,
            "capabilities": sorted(device.capabilities),
            "root_available": device.root_available,
        }

    @application.post(
        "/api/v1/devices/{device_id}/capabilities/refresh", dependencies=[Depends(control)]
    )
    async def refresh_capabilities(device_id: str) -> DeviceResponse:
        return response(await service.refresh_capabilities(device_id))

    @application.get("/api/v1/devices/{device_id}/metrics")
    async def current_metrics(device_id: str) -> CurrentMetricsResponse:
        device = service.get(device_id)
        snapshot = service.snapshots.get(device_id)
        stale = False
        if snapshot is not None:
            age = (datetime.now(UTC) - snapshot.observed_at).total_seconds()
            stale = age < 0 or age > configuration.metrics_max_age_seconds
        result = current_response(device, snapshot, stale=stale)
        if stale or device.state != DeviceState.ONLINE:
            result.values = []
        return result

    @application.get("/api/v1/devices/{device_id}/metrics/history")
    async def historical_metrics(
        device_id: str,
        start: datetime,
        end: datetime,
        metric: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=1000, ge=1, le=10000),
        cursor: str | None = Query(default=None, max_length=2048),
    ) -> HistoryResponse:
        service.get(device_id)
        page = await metric_history.query(
            device_id, start=start, end=end, metric=metric, limit=limit, cursor=cursor
        )
        return history_response(device_id, start, end, page)

    @application.get("/metrics")
    async def metrics() -> Response:
        last_evaluation = alert_engine.last_evaluation_at
        last_timestamp = last_evaluation.timestamp() if last_evaluation else 0
        return Response(
            render_metrics(
                list(service.devices.values()),
                service.snapshots,
                max_age_seconds=configuration.metrics_max_age_seconds,
            )
            + (
                f"android_alert_evaluation_healthy {int(alert_engine.healthy)}\n"
                f"android_alert_evaluations_total {alert_engine.evaluations_total}\n"
                f"android_alert_evaluation_errors_total {alert_engine.evaluation_errors_total}\n"
                "android_alert_evaluation_duration_seconds "
                f"{alert_engine.last_evaluation_duration}\n"
                f"android_alert_last_evaluation_timestamp_seconds {last_timestamp}\n"
            ).encode()
            + render_screen_metrics(screens.metrics())
            + render_terminal_metrics(terminals).encode(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return application


app = create_app()
