"""Application-owned role authorization and append-only security audit storage."""

import asyncio
import hashlib
import hmac
import json
import math
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from android_fleet.core.settings import Settings

READ = frozenset(
    {
        "device.read",
        "telemetry.read",
        "alerts.read",
        "operations.read",
        "screen:view",
        "terminal:view",
    }
)
OPERATOR = READ | {
    "control.inspect",
    "control.screen",
    "apps.launch",
    "apps.stop",
    "operations.cancel",
    "screen:control",
    "screen:session:terminate",
}
ADMIN = OPERATOR | {
    "device.manage",
    "alerts.manage",
    "apps.install",
    "apps.uninstall",
    "control.reboot",
    "control.reboot_special",
    "audit.read",
    "security.manage",
    "terminal:adb",
    "terminal:ssh",
    "terminal:profile:manage",
    "terminal:session:terminate",
}
ROLE_PERMISSIONS = {"viewer": READ, "operator": OPERATOR, "administrator": ADMIN}


@dataclass(frozen=True)
class Actor:
    identity: str
    role: str
    permissions: frozenset[str]
    device_ids: frozenset[str] | None = None


class SecurityService:
    def __init__(self, settings: Settings, path: str | Path) -> None:
        self.path = Path(path)
        self.anonymous_viewer = getattr(settings, "anonymous_viewer", False)
        self.retention = int(getattr(settings, "audit_retention_seconds", 90 * 86400))
        self._credentials: list[tuple[str, Actor]] = []
        legacy = settings.control_token
        if legacy:
            self._credentials.append(
                (
                    self._digest(legacy.get_secret_value()),
                    Actor("legacy-administrator", "administrator", ADMIN),
                )
            )
        configured = getattr(settings, "rbac_credentials", None)
        if configured:
            raw = (
                configured.get_secret_value()
                if hasattr(configured, "get_secret_value")
                else configured
            )
            try:
                records = json.loads(raw)
                if not isinstance(records, list):
                    raise ValueError
                identities: set[str] = {"anonymous", "unauthenticated", "legacy-administrator"}
                hashes: set[str] = set()
                for record in records:
                    identity, role, digest = (
                        record["identity"],
                        record["role"],
                        record["token_hash"],
                    )
                    if (
                        not isinstance(identity, str)
                        or not re.fullmatch(r"[\w.@-]{1,80}", identity)
                        or role not in ROLE_PERMISSIONS
                        or not isinstance(digest, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", digest)
                        or identity in identities
                        or digest in hashes
                    ):
                        raise ValueError
                    identities.add(identity)
                    hashes.add(digest)
                    scope = record.get("device_ids")
                    explicit = record.get("permissions", [])
                    terminal_permissions = {
                        "terminal:adb",
                        "terminal:ssh",
                        "terminal:session:terminate",
                    }
                    if (
                        not isinstance(explicit, list)
                        or any(item not in terminal_permissions for item in explicit)
                        or (role == "viewer" and explicit)
                    ):
                        raise ValueError
                    if scope is not None and (
                        not isinstance(scope, list)
                        or any(
                            not isinstance(item, str) or not item or len(item) > 128
                            for item in scope
                        )
                    ):
                        raise ValueError
                    self._credentials.append(
                        (
                            digest,
                            Actor(
                                identity,
                                role,
                                ROLE_PERMISSIONS[role] | frozenset(explicit),
                                frozenset(scope) if scope is not None else None,
                            ),
                        )
                    )
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("Invalid RBAC credential configuration") from exc
        if len({digest for digest, _ in self._credentials}) != len(self._credentials):
            raise ValueError("Duplicate RBAC credential")

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("Audit database schema is newer than this application")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA user_version=1;
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
                    actor TEXT NOT NULL, role TEXT NOT NULL, device_id TEXT,
                    action TEXT NOT NULL, request_id TEXT NOT NULL,
                    authorization TEXT NOT NULL, outcome TEXT NOT NULL,
                    duration REAL NOT NULL, error TEXT
                );
                CREATE INDEX IF NOT EXISTS audit_timestamp ON audit(timestamp);
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit records are immutable'); END;
            """)
        self.path.chmod(0o600)
        self._cleanup()

    async def close(self) -> None:
        pass

    def actor(self, request: Request) -> Actor | None:
        authorization = request.headers.get("authorization", "")
        token = request.headers.get("x-control-token", "")
        if authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() != "bearer" or not value:
                return None
            token = value
        if token:
            digest = self._digest(token)
            for expected, actor in self._credentials:
                if hmac.compare_digest(digest, expected):
                    return actor
            return None
        return Actor("anonymous", "viewer", READ) if self.anonymous_viewer else None

    async def authorize(self, request: Request, permission: str) -> Actor:
        actor = self.actor(request)
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        request.state.request_id = request_id
        if (
            actor is None
            or permission not in actor.permissions
            or (permission.startswith(("screen:", "terminal:")) and actor.identity == "anonymous")
        ):
            await self.audit(
                actor or Actor("unauthenticated", "none", frozenset()),
                request.path_params.get("device_id")
                or getattr(request.state, "audit_device_id", None),
                getattr(request.state, "audit_action", permission),
                request_id,
                "denied",
                "rejected",
                error="permission_denied",
            )
            raise HTTPException(401 if actor is None else 403, "Permission denied")
        request.state.actor = actor
        return actor

    async def authorize_device(self, actor: Actor, device_id: str, permission: str) -> None:
        if (
            permission not in actor.permissions
            or (actor.device_ids is not None and device_id not in actor.device_ids)
            or actor.identity == "anonymous"
        ):
            await self.audit(
                actor,
                device_id,
                permission,
                str(uuid.uuid4()),
                "denied",
                "rejected",
                error="permission_denied",
            )
            raise HTTPException(403, "Permission denied")

    async def audit(
        self,
        actor: Actor,
        device_id: str | None,
        action: str,
        request_id: str,
        authorization: str,
        outcome: str,
        duration: float = 0,
        error: str | None = None,
    ) -> None:
        # Error details intentionally accept only machine codes, never exception messages or output.
        safe_error = error if error and re.fullmatch(r"[a-z_]{1,64}", error) else None
        values = (
            time.time(),
            actor.identity,
            actor.role,
            device_id,
            action,
            request_id,
            authorization,
            outcome,
            max(0, duration) if math.isfinite(duration) else 0,
            safe_error,
        )
        await asyncio.to_thread(self._append, values)

    def _append(self, values: tuple[Any, ...]) -> None:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                "INSERT INTO audit(timestamp,actor,role,device_id,action,request_id,"
                "authorization,outcome,duration,error) VALUES(?,?,?,?,?,?,?,?,?,?)",
                values,
            )

    def _cleanup(self) -> None:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("DELETE FROM audit WHERE timestamp < ?", (time.time() - self.retention,))

    async def cleanup(self) -> None:
        """Retention maintenance; no public mutation route is provided."""
        await asyncio.to_thread(self._cleanup)

    async def history(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        actor: str | None = None,
        device_id: str | None = None,
        action: str | None = None,
        authorization: str | None = None,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Invalid audit pagination")
        filters = {
            "actor": actor,
            "device_id": device_id,
            "action": action,
            "authorization": authorization,
            "outcome": outcome,
        }

        def read() -> dict[str, Any]:
            clauses = [f"{key} = ?" for key, value in filters.items() if value is not None]
            args = [value for value in filters.values() if value is not None]
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with sqlite3.connect(self.path, timeout=30) as db:
                db.row_factory = sqlite3.Row
                total = db.execute("SELECT COUNT(*) FROM audit" + where, args).fetchone()[0]
                rows = db.execute(
                    "SELECT * FROM audit" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                    [*args, limit, offset],
                )
                return {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

        return await asyncio.to_thread(read)

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/v1")

        @router.get("/auth/me")
        async def me(request: Request) -> dict[str, Any]:
            actor = await self.authorize(request, "device.read")
            return {
                "identity": actor.identity,
                "role": actor.role,
                "permissions": sorted(actor.permissions),
            }

        @router.get("/audit")
        async def audit_history(
            request: Request,
            limit: int = Query(50, ge=1, le=200),
            offset: int = Query(0, ge=0),
            actor: str | None = None,
            device_id: str | None = None,
            action: str | None = None,
            authorization: str | None = None,
            outcome: str | None = None,
        ) -> dict[str, Any]:
            await self.authorize(request, "audit.read")
            return await self.history(
                limit=limit,
                offset=offset,
                actor=actor,
                device_id=device_id,
                action=action,
                authorization=authorization,
                outcome=outcome,
            )

        return router
