"""Administrator-only Wireless Debugging enrollment; pairing codes are never persisted."""

import asyncio
import ipaddress
import sqlite3
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from android_fleet.adb.base import AdbClient
from android_fleet.core.settings import Settings, normalize_pairing_network
from android_fleet.devices.models import ConnectionType, DeviceState
from android_fleet.devices.probe import parse_getprop
from android_fleet.devices.registry_models import DeviceRegistration
from android_fleet.devices.service import FleetService
from android_fleet.security import Actor, SecurityService


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(ge=1024, le=65535, strict=True)

    @field_validator("host")
    @classmethod
    def ip_literal(cls, value: str) -> str:
        address = ipaddress.ip_address(value)
        if (
            not address.is_private
            or address.is_loopback
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
            or "%" in value
        ):
            raise ValueError("A private LAN IP address is required")
        # Limit IPv4 to RFC1918 and IPv6 to ULA, rather than reserved service ranges.
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
        if not any(address in ipaddress.ip_network(net) for net in networks):
            raise ValueError("A private LAN IP address is required")
        return str(address)

    @property
    def address(self) -> str:
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"


class PairRequest(Endpoint):
    code: SecretStr

    @field_validator("code")
    @classmethod
    def six_digits(cls, value: SecretStr) -> SecretStr:
        code = value.get_secret_value()
        if len(code) != 6 or not code.isascii() or not code.isdecimal():
            raise ValueError("Six digits required")
        return value


class RegistrationRequest(Endpoint):
    name: str = Field(min_length=1, max_length=128)


class NetworkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network: str = Field(min_length=1, max_length=64)

    @field_validator("network")
    @classmethod
    def validate_network(cls, value: str) -> str:
        try:
            return normalize_pairing_network(value)
        except ValueError as exc:
            raise ValueError("Enter a private IP or bounded private LAN CIDR") from exc


class PairingService:
    def __init__(
        self,
        adb: AdbClient,
        fleet: FleetService,
        security: SecurityService,
        settings: Settings,
        path: str | Path,
    ) -> None:
        self.adb, self.fleet, self.security, self.settings = adb, fleet, security, settings
        self.path = Path(path)
        self.approved_networks: set[str] = set()
        self.network_lock = asyncio.Lock()
        self.attempts: dict[str, deque[float]] = {}
        self.lock = asyncio.Lock()
        self.verified: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS approved_networks ("
                "network TEXT PRIMARY KEY, created_at REAL NOT NULL, created_by TEXT NOT NULL)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS pairing_settings (key TEXT PRIMARY KEY)")
            initialized = db.execute(
                "SELECT 1 FROM pairing_settings WHERE key='network_seeded'"
            ).fetchone()
            if initialized is None:
                db.executemany(
                    "INSERT OR IGNORE INTO approved_networks(network,created_at,created_by) "
                    "VALUES(?,?,?)",
                    (
                        (network, time.time(), "environment")
                        for network in self.settings.pairing_allowed_hosts
                    ),
                )
                db.execute("INSERT INTO pairing_settings(key) VALUES('network_seeded')")
            self.approved_networks = {
                row[0] for row in db.execute("SELECT network FROM approved_networks")
            }

    def _network_records(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT network,created_at,created_by FROM approved_networks ORDER BY network"
            ).fetchall()
        return [dict(row) for row in rows]

    async def network_records(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._network_records)

    def _add_network(self, network: str, actor: str) -> None:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                "INSERT OR IGNORE INTO approved_networks(network,created_at,created_by) "
                "VALUES(?,?,?)",
                (network, time.time(), actor),
            )

    async def add_network(self, network: str, actor: str) -> list[dict[str, Any]]:
        normalized = normalize_pairing_network(network)
        async with self.network_lock:
            await asyncio.to_thread(self._add_network, normalized, actor)
            self.approved_networks.add(normalized)
            return await self.network_records()

    def _remove_network(self, network: str) -> None:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("DELETE FROM approved_networks WHERE network=?", (network,))

    async def remove_network(self, network: str) -> list[dict[str, Any]]:
        normalized = normalize_pairing_network(network)
        async with self.network_lock:
            await asyncio.to_thread(self._remove_network, normalized)
            self.approved_networks.discard(normalized)
            return await self.network_records()

    def destination(self, endpoint: Endpoint) -> None:
        address = ipaddress.ip_address(endpoint.host)
        if not any(
            address in ipaddress.ip_network(approved) for approved in self.approved_networks
        ):
            raise HTTPException(
                403,
                "Destination is not approved. An administrator can approve this private IP or "
                "CIDR in Device management → Wireless Debugging network access.",
            )

    def rate_limit(self, actor: Actor) -> None:
        now = time.monotonic()
        attempts = self.attempts.setdefault(actor.identity, deque())
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= self.settings.pairing_attempts_per_minute:
            raise HTTPException(429, "Wireless Debugging attempt limit reached")
        attempts.append(now)

    async def audited(self, actor: Actor, action: str, body: Endpoint) -> dict[str, Any]:
        outcome = "failed"
        error: str | None = "connection_failed"
        try:
            self.destination(body)
            self.rate_limit(actor)
            async with asyncio.timeout(self.settings.pairing_timeout), self.lock:
                if isinstance(body, PairRequest):
                    result = await self.adb.pair(
                        body.address,
                        body.code.get_secret_value(),
                        timeout=self.settings.pairing_timeout,
                    )
                    if result.timeout:
                        raise TimeoutError
                    if result.exit_code != 0 or result.stdout != "paired":
                        raise HTTPException(
                            409,
                            "Pairing failed: check the current code, pairing port and reachability",
                        )
                    outcome, error = "succeeded", None
                    return {"paired": True, "connected": False}
                result = await self.adb.connect(body.address)
                if result.timeout:
                    raise TimeoutError
                if result.exit_code != 0:
                    raise HTTPException(
                        409, "Connection failed: verify the separate connection port"
                    )
                state = (await self.adb.list_devices()).get(body.address)
                if state != DeviceState.ONLINE:
                    raise HTTPException(409, "Device is not online and authorized")
                properties = await self.adb.shell(body.address, ("getprop",), timeout=5)
                if properties.exit_code != 0 or properties.timeout:
                    raise HTTPException(409, "Device verification failed")
                values = parse_getprop(properties.stdout)
                data = {
                    "connected": True,
                    "serial": body.address,
                    "model": values.get("ro.product.model"),
                    "manufacturer": values.get("ro.product.manufacturer"),
                    "android_version": values.get("ro.build.version.release"),
                    "stable_identity": values.get("ro.serialno") or values.get("ro.boot.serialno"),
                }
                self.verified[(actor.identity, body.host, body.port)] = (time.monotonic(), data)
                # Bound ephemeral verification cache; never retain pairing codes.
                self.verified = {
                    key: val
                    for key, val in self.verified.items()
                    if val[0] > time.monotonic() - 300
                }
                outcome, error = "succeeded", None
                return data
        except HTTPException as exc:
            error = (
                "permission_denied"
                if exc.status_code == 403
                else "rate_limited"
                if exc.status_code == 429
                else "connection_failed"
            )
            raise
        except TimeoutError as exc:
            error = "connection_timeout"
            raise HTTPException(504, "Wireless Debugging operation timed out") from exc
        except (OSError, RuntimeError) as exc:
            error = "adb_unavailable"
            raise HTTPException(503, "ADB service is unavailable") from exc
        finally:
            await self.security.audit(
                actor,
                None,
                action,
                str(uuid.uuid4()),
                "denied" if error == "permission_denied" else "allowed",
                outcome,
                error=error,
            )

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/v1")

        async def admin(request: Request) -> Actor:
            return await self.security.authorize(request, "security.manage")

        @router.get("/pairing/allowed-networks")
        async def list_networks(request: Request) -> dict[str, Any]:
            await admin(request)
            return {"networks": await self.network_records()}

        @router.post("/pairing/allowed-networks")
        async def approve_network(body: NetworkRequest, request: Request) -> dict[str, Any]:
            actor = await admin(request)
            networks = await self.add_network(body.network, actor.identity)
            await self.security.audit(
                actor,
                None,
                "pairing.network.approve",
                getattr(request.state, "request_id", str(uuid.uuid4())),
                "allowed",
                "succeeded",
            )
            return {"networks": networks}

        @router.delete("/pairing/allowed-networks")
        async def revoke_network(body: NetworkRequest, request: Request) -> dict[str, Any]:
            actor = await admin(request)
            networks = await self.remove_network(body.network)
            await self.security.audit(
                actor,
                None,
                "pairing.network.revoke",
                getattr(request.state, "request_id", str(uuid.uuid4())),
                "allowed",
                "succeeded",
            )
            return {"networks": networks}

        @router.post("/pairing/pair")
        async def pair(body: PairRequest, request: Request) -> dict[str, Any]:
            return await self.audited(await admin(request), "device.pair", body)

        @router.post("/pairing/connect")
        async def connect(body: Endpoint, request: Request) -> dict[str, Any]:
            return await self.audited(await admin(request), "device.wireless_connect", body)

        @router.post("/pairing/register", status_code=201)
        async def register(body: RegistrationRequest, request: Request) -> dict[str, Any]:
            actor = await admin(request)
            self.destination(body)
            verified = self.verified.get((actor.identity, body.host, body.port))
            if not verified or verified[0] < time.monotonic() - 300:
                raise HTTPException(409, "Connect and verify the device before registration")
            if (await self.adb.list_devices()).get(body.address) != DeviceState.ONLINE:
                raise HTTPException(409, "Device disconnected before registration")
            identity = verified[1].get("stable_identity")
            if identity and any(
                config.metadata.get("wireless_identity") == identity
                for config in self.fleet.configs.values()
            ):
                raise HTTPException(409, "Device is already registered; update its connection port")
            device = await self.fleet.register(
                DeviceRegistration(
                    body.name,
                    ConnectionType.WIRELESS_ADB,
                    body.host,
                    body.port,
                    metadata={"wireless_identity": identity} if identity else {},
                )
            )
            await self.security.audit(
                actor,
                device.id,
                "device.wireless_register",
                str(uuid.uuid4()),
                "allowed",
                "succeeded",
            )
            return {"id": device.id}

        @router.post("/devices/{device_id}/wireless-port")
        async def update_port(device_id: str, body: Endpoint, request: Request) -> dict[str, Any]:
            actor = await admin(request)
            await self.security.authorize_device(actor, device_id, "device.manage")
            current = self.fleet.configs.get(device_id)
            if not current or current.connection_type != ConnectionType.WIRELESS_ADB:
                raise HTTPException(409, "Registered Wireless Debugging device required")
            data = await self.audited(actor, "device.wireless_update_verify", body)
            identity = current.metadata.get("wireless_identity")
            if identity and identity != data.get("stable_identity"):
                raise HTTPException(409, "The endpoint belongs to a different device")
            if not identity and body.host != current.host:
                raise HTTPException(
                    409, "Device identity unavailable; host changes require registration"
                )
            device = await self.fleet.patch(
                device_id,
                lambda config: DeviceRegistration(
                    name=config.name,
                    connection_type=config.connection_type,
                    host=body.host,
                    port=body.port,
                    serial=config.serial,
                    mdns_service=config.mdns_service,
                    metadata=config.metadata,
                    auto_connect=config.auto_connect,
                ),
            )
            await self.security.audit(
                actor,
                device_id,
                "device.wireless_port_update",
                str(uuid.uuid4()),
                "allowed",
                "succeeded",
            )
            return {"id": device.id, "port": body.port, "state": device.state}

        return router
