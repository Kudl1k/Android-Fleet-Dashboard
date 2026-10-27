"""Encrypted SSH profiles and explicit destination/identity authorization."""

import asyncio
import ipaddress
import re
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from android_fleet.security import Actor, SecurityService


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    username: str = Field(min_length=1, max_length=128)
    auth_method: Literal["key", "password"] = "key"
    device_id: str | None = Field(default=None, max_length=128)
    enabled: bool = Field(default=True, strict=True)
    allowed_identities: list[str] = Field(default_factory=list, max_length=100)
    credential: SecretStr | None = Field(default=None, min_length=1, max_length=65536)

    @field_validator("allowed_identities")
    @classmethod
    def valid_identities(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[\w.@-]{1,80}", value) for value in values):
            raise ValueError("Invalid identity")
        return list(dict.fromkeys(values))

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9.:-]+", value):
            raise ValueError("Invalid host")
        return value.lower()

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        if not re.fullmatch(r"[\w.@-]+", value):
            raise ValueError("Invalid username")
        return value


class Profile(ProfileInput):
    id: str
    created_at: float
    updated_at: float
    fingerprint: str | None = None
    credential_ref: str
    destination_ip: str
    credential: SecretStr | None = Field(default=None, exclude=True)


PROHIBITED_PORTS = frozenset({2375, 2376, 5037})


def normalize_destination(value: str) -> str:
    """Return a canonical ``host:port`` entry; IPv6 hosts may be written in brackets."""
    host, separator, port_text = value.strip().lower().rpartition(":")
    host = host.removeprefix("[").removesuffix("]")
    if not separator or not port_text.isdecimal() or not re.fullmatch(r"[a-z0-9.:-]{1,253}", host):
        raise ValueError("Enter an SSH destination as host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ValueError("Enter an SSH destination as host:port")
    if port in PROHIBITED_PORTS:
        raise ValueError("SSH destination port is prohibited")
    return f"{host}:{port}"


class DestinationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str = Field(min_length=3, max_length=260)

    @field_validator("destination")
    @classmethod
    def valid_destination(cls, value: str) -> str:
        return normalize_destination(value)


class FingerprintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(min_length=10, max_length=150)


class ProfileService:
    def __init__(self, path: Path, encryption_key: str | None, destinations: list[str]) -> None:
        self._mutation_lock = asyncio.Lock()
        self.path = path
        self.cipher = Fernet(encryption_key.encode()) if encryption_key else None
        self.seed_destinations = tuple(destinations)
        self.destinations: set[str] = set()

    async def initialize(self) -> None:
        def init() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS ssh_profiles "
                    "(id TEXT PRIMARY KEY, profile TEXT NOT NULL, secret BLOB NOT NULL, "
                    "host_key TEXT)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS termux_destinations "
                    "(device_id TEXT PRIMARY KEY, host TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS approved_destinations (destination TEXT PRIMARY "
                    "KEY, created_at REAL NOT NULL, created_by TEXT NOT NULL)"
                )
                db.execute("CREATE TABLE IF NOT EXISTS ssh_settings (key TEXT PRIMARY KEY)")
                seeded = db.execute(
                    "SELECT 1 FROM ssh_settings WHERE key='destinations_seeded'"
                ).fetchone()
                if seeded is None:
                    # The environment only seeds the first start; the dashboard owns it after.
                    for value in self.seed_destinations:
                        try:
                            destination = normalize_destination(value)
                        except ValueError:
                            continue
                        db.execute(
                            "INSERT OR IGNORE INTO approved_destinations VALUES(?,?,?)",
                            (destination, time.time(), "environment"),
                        )
                    db.execute("INSERT INTO ssh_settings(key) VALUES('destinations_seeded')")
                self.destinations = {
                    row[0] for row in db.execute("SELECT destination FROM approved_destinations")
                }
            self.path.chmod(0o600)

        await asyncio.to_thread(init)

    async def _query(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        def run() -> list[tuple[Any, ...]]:
            with sqlite3.connect(self.path, timeout=30) as db:
                return db.execute(sql, args).fetchall()

        return await asyncio.to_thread(run)

    async def destination_records(self) -> list[dict[str, Any]]:
        rows = await self._query(
            "SELECT destination,created_at,created_by FROM approved_destinations "
            "ORDER BY destination"
        )
        return [{"destination": row[0], "created_at": row[1], "created_by": row[2]} for row in rows]

    async def add_destination(self, destination: str, actor: str) -> list[dict[str, Any]]:
        normalized = normalize_destination(destination)
        async with self._mutation_lock:
            await self._query(
                "INSERT OR IGNORE INTO approved_destinations VALUES(?,?,?)",
                (normalized, time.time(), actor),
            )
            self.destinations.add(normalized)
            return await self.destination_records()

    async def remove_destination(self, destination: str) -> list[dict[str, Any]]:
        normalized = normalize_destination(destination)
        async with self._mutation_lock:
            await self._query(
                "DELETE FROM approved_destinations WHERE destination=?", (normalized,)
            )
            self.destinations.discard(normalized)
            return await self.destination_records()

    async def get(self, profile_id: str) -> Profile:
        rows = await self._query("SELECT profile FROM ssh_profiles WHERE id=?", (profile_id,))
        if not rows:
            raise HTTPException(404, "SSH profile not found")
        return Profile.model_validate_json(rows[0][0])

    async def list(self, actor: Actor) -> list[Profile]:
        rows = await self._query("SELECT profile FROM ssh_profiles ORDER BY id")
        profiles = [Profile.model_validate_json(row[0]) for row in rows]
        return [
            p
            for p in profiles
            if actor.role == "administrator" or actor.identity in p.allowed_identities
        ]

    async def destination(self, profile: ProfileInput) -> str:
        if f"{profile.host}:{profile.port}" not in self.destinations:
            approved = bool(
                profile.device_id
                and profile.port == 8022
                and await self._query(
                    "SELECT 1 FROM termux_destinations WHERE device_id=? AND host=?",
                    (profile.device_id, profile.host),
                )
            )
            if not approved:
                raise HTTPException(
                    403,
                    f"SSH destination {profile.host}:{profile.port} is not approved. An "
                    "administrator can approve it under SSH destination access.",
                )
        if profile.port in PROHIBITED_PORTS:
            raise HTTPException(403, "SSH destination port is prohibited")
        loop = asyncio.get_running_loop()
        try:
            addresses = await asyncio.wait_for(
                loop.getaddrinfo(profile.host, profile.port, type=socket.SOCK_STREAM), 5
            )
        except (OSError, TimeoutError) as exc:
            raise HTTPException(400, "SSH destination resolution failed") from exc
        ips = {str(item[4][0]) for item in addresses}
        for value in ips:
            ip = ipaddress.ip_address(value)
            if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
                raise HTTPException(403, "SSH destination address is prohibited")
        if not ips:
            raise HTTPException(400, "SSH destination resolution failed")
        pinned = getattr(profile, "destination_ip", None)
        if pinned and pinned not in ips:
            raise HTTPException(409, "SSH destination address changed; edit profile to reapprove")
        return pinned or sorted(ips)[0]

    async def authorize(self, profile_id: str, actor: Actor) -> Profile:
        profile = await self.get(profile_id)
        if (
            "terminal:ssh" not in actor.permissions
            or not profile.enabled
            or (actor.role != "administrator" and actor.identity not in profile.allowed_identities)
            or (
                profile.device_id
                and actor.device_ids is not None
                and profile.device_id not in actor.device_ids
            )
        ):
            raise HTTPException(403, "SSH profile access denied")
        return profile

    async def save(self, body: ProfileInput, profile_id: str | None = None) -> Profile:
        async with self._mutation_lock:
            return await self._save(body, profile_id)

    async def _save(
        self,
        body: ProfileInput,
        profile_id: str | None = None,
        *,
        new_id: str | None = None,
    ) -> Profile:
        address = await self.destination(body)
        if self.cipher is None:
            raise HTTPException(503, "SSH encryption key is not configured")
        old = await self.get(profile_id) if profile_id else None
        if not old and not body.credential:
            raise HTTPException(422, "SSH credential required")
        if old and body.auth_method != old.auth_method and not body.credential:
            raise HTTPException(422, "Replacement credential required")
        pid = profile_id or new_id or str(uuid.uuid4())
        profile = Profile(
            **body.model_dump(exclude={"credential"}),
            id=pid,
            created_at=old.created_at if old else time.time(),
            updated_at=time.time(),
            fingerprint=old.fingerprint
            if old and (old.host, old.port) == (body.host, body.port)
            else None,
            credential_ref=pid,
            destination_ip=address,
        )
        if body.credential:
            raw = body.credential.get_secret_value()
            if len(raw) > 65536 or not raw:
                raise HTTPException(422, "Invalid SSH credential")
            if body.auth_method == "key":
                import asyncssh

                try:
                    asyncssh.import_private_key(raw)
                except (ValueError, asyncssh.KeyImportError) as exc:
                    raise HTTPException(422, "Invalid SSH private key") from exc
            secret = self.cipher.encrypt(raw.encode())
        else:
            secret = (await self._query("SELECT secret FROM ssh_profiles WHERE id=?", (pid,)))[0][0]
        key = None
        if old and profile.fingerprint:
            key = (await self._query("SELECT host_key FROM ssh_profiles WHERE id=?", (pid,)))[0][0]
        await self._query(
            "INSERT OR REPLACE INTO ssh_profiles VALUES(?,?,?,?)",
            (pid, profile.model_dump_json(), secret, key),
        )
        return profile

    @staticmethod
    def validate_termux_host(host: str) -> None:
        try:
            address = ipaddress.ip_address(host)
            if (
                not any(
                    address in ipaddress.ip_network(net)
                    for net in (
                        "10.0.0.0/8",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "fc00::/7",
                    )
                )
                or "%" in host
            ):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(403, "Termux setup requires a private LAN IP address") from exc

    async def prepare_termux(
        self,
        device_id: str,
        host: str,
        name: str,
        username: str,
    ) -> Profile:
        """Explicit setup authorizes one device's port 8022, with an encrypted key."""
        import asyncssh

        self.validate_termux_host(host)
        async with self._mutation_lock:
            if self.cipher is None:
                raise HTTPException(503, "SSH encryption key is not configured")
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, "android-fleet:termux:" + device_id))
            rows = await self._query("SELECT profile FROM ssh_profiles WHERE id=?", (pid,))
            old = Profile.model_validate_json(rows[0][0]) if rows else None
            secret = (
                None
                if old
                else SecretStr(
                    asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()
                )
            )
            await self._query(
                "INSERT OR REPLACE INTO termux_destinations VALUES(?,?)",
                (device_id, host),
            )
            return await self._save(
                ProfileInput(
                    name=("Termux SSH · " + name)[:100],
                    host=host,
                    port=8022,
                    username=username,
                    auth_method="key",
                    device_id=device_id,
                    enabled=False,
                    allowed_identities=old.allowed_identities if old else [],
                    credential=secret,
                ),
                pid if old else None,
                new_id=pid,
            )

    async def complete_termux(self, profile_id: str, key: Any) -> None:
        """Pin a host key already verified through the authenticated ADB tunnel."""
        async with self._mutation_lock:
            profile = await self.get(profile_id)
            profile.enabled = True
            profile.fingerprint = key.get_fingerprint("sha256")
            profile.updated_at = time.time()
            await self._query(
                "UPDATE ssh_profiles SET profile=?,host_key=? WHERE id=?",
                (profile.model_dump_json(), key.export_public_key().decode(), profile_id),
            )

    async def credentials(self, profile: Profile) -> str:
        async with self._mutation_lock:
            return await self._credentials(profile)

    async def _credentials(self, profile: Profile) -> str:
        if self.cipher is None:
            raise HTTPException(503, "SSH encryption key is not configured")
        rows = await self._query("SELECT secret FROM ssh_profiles WHERE id=?", (profile.id,))
        if not rows:
            raise HTTPException(404, "SSH profile not found")
        try:
            return self.cipher.decrypt(rows[0][0]).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise HTTPException(503, "SSH credential unavailable; check encryption key") from exc

    async def rotate_encryption_key(self, encryption_key: str) -> None:
        async with self._mutation_lock:
            await self._rotate_encryption_key(encryption_key)

    async def _rotate_encryption_key(self, encryption_key: str) -> None:
        """Atomically reencrypt credentials; caller separately replaces managed key."""
        if self.cipher is None:
            raise ValueError("Existing encryption key is required")
        replacement = Fernet(encryption_key.encode())
        current = self.cipher

        def rotate() -> None:
            with sqlite3.connect(self.path, timeout=30) as db:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute("SELECT id,secret FROM ssh_profiles").fetchall()
                for profile_id, encrypted in rows:
                    db.execute(
                        "UPDATE ssh_profiles SET secret=? WHERE id=?",
                        (replacement.encrypt(current.decrypt(encrypted)), profile_id),
                    )

        await asyncio.to_thread(rotate)
        self.cipher = replacement

    async def host_key(self, profile_id: str) -> str | None:
        rows = await self._query("SELECT host_key FROM ssh_profiles WHERE id=?", (profile_id,))
        return str(rows[0][0]) if rows and rows[0][0] else None

    def router(self, security: SecurityService) -> APIRouter:
        from android_fleet.terminal.ssh import SSHGateway

        gateway = SSHGateway(self)
        router = APIRouter(prefix="/api/v1/ssh/profiles", tags=["SSH profiles"])
        destinations = APIRouter(prefix="/api/v1/ssh/destinations", tags=["SSH profiles"])

        async def audit(actor: Actor, action: str) -> None:
            await security.audit(actor, None, action, str(uuid.uuid4()), "allowed", "success")

        @destinations.get("")
        async def list_destinations(request: Request) -> dict[str, Any]:
            await security.authorize(request, "terminal:profile:manage")
            return {"destinations": await self.destination_records()}

        @destinations.post("")
        async def approve_destination(request: Request, body: DestinationInput) -> dict[str, Any]:
            actor = await security.authorize(request, "terminal:profile:manage")
            records = await self.add_destination(body.destination, actor.identity)
            await audit(actor, "terminal.destination.approve")
            return {"destinations": records}

        @destinations.delete("")
        async def revoke_destination(request: Request, body: DestinationInput) -> dict[str, Any]:
            actor = await security.authorize(request, "terminal:profile:manage")
            records = await self.remove_destination(body.destination)
            await audit(actor, "terminal.destination.revoke")
            return {"destinations": records}

        @router.get("")
        async def listing(request: Request) -> list[Profile]:
            actor = await security.authorize(request, "terminal:view")
            return await self.list(actor)

        @router.post("")
        async def create(request: Request, body: ProfileInput) -> Profile:
            actor = await security.authorize(request, "terminal:profile:manage")
            result = await self.save(body)
            await audit(actor, "terminal.profile.create")
            if body.credential:
                await audit(actor, "terminal.credential.change")
            return result

        @router.put("/{profile_id}")
        async def update(request: Request, profile_id: str, body: ProfileInput) -> Profile:
            actor = await security.authorize(request, "terminal:profile:manage")
            result = await self.save(body, profile_id)
            await audit(actor, "terminal.profile.update")
            if body.credential:
                await audit(actor, "terminal.credential.change")
            return result

        @router.delete("/{profile_id}")
        async def delete(request: Request, profile_id: str) -> dict[str, str]:
            actor = await security.authorize(request, "terminal:profile:manage")
            async with self._mutation_lock:
                await self.get(profile_id)
                await self._query("DELETE FROM ssh_profiles WHERE id=?", (profile_id,))
            await audit(actor, "terminal.profile.delete")
            return {"status": "deleted"}

        @router.get("/{profile_id}/host-key")
        async def candidate(request: Request, profile_id: str) -> dict[str, str]:
            await security.authorize(request, "terminal:profile:manage")
            key = await gateway.candidate(profile_id)
            return {"fingerprint": key.get_fingerprint("sha256")}

        @router.post("/{profile_id}/host-key")
        async def approve(
            request: Request, profile_id: str, body: FingerprintInput
        ) -> dict[str, str]:
            actor = await security.authorize(request, "terminal:profile:manage")
            async with self._mutation_lock:
                key = await gateway.candidate(profile_id)
                if key.get_fingerprint("sha256") != body.fingerprint:
                    raise HTTPException(409, "SSH host key fingerprint changed")
                profile = await self.get(profile_id)
                action = (
                    "terminal.host_key.replace"
                    if profile.fingerprint
                    else "terminal.host_key.approve"
                )
                profile.fingerprint = body.fingerprint
                profile.updated_at = time.time()
                await self._query(
                    "UPDATE ssh_profiles SET profile=?,host_key=? WHERE id=?",
                    (profile.model_dump_json(), key.export_public_key().decode(), profile_id),
                )
                await audit(actor, action)
            return {"fingerprint": body.fingerprint}

        @router.post("/{profile_id}/test")
        async def test(request: Request, profile_id: str) -> dict[str, str]:
            actor = await security.authorize(request, "terminal:profile:manage")
            try:
                transport = await gateway.open(profile_id, actor, 80, 24)
                await transport.close()
            except HTTPException as exc:
                await security.audit(
                    actor,
                    None,
                    "terminal.profile.test",
                    str(uuid.uuid4()),
                    "denied" if exc.status_code == 403 else "allowed",
                    "failed",
                    error="permission_denied" if exc.status_code == 403 else "connection_failed",
                )
                raise
            await audit(actor, "terminal.profile.test")
            return {"status": "connected"}

        combined = APIRouter()
        combined.include_router(router)
        combined.include_router(destinations)
        return combined
