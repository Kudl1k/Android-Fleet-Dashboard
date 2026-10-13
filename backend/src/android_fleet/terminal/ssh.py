"""AsyncSSH gateway with explicit credentials, IP dialing and pinned host keys."""

import asyncio

import asyncssh
from fastapi import HTTPException

from android_fleet.security import Actor
from android_fleet.terminal.profiles import ProfileService


class SSHTransport:
    def __init__(
        self, connection: asyncssh.SSHClientConnection, process: asyncssh.SSHClientProcess[bytes]
    ) -> None:
        self.connection = connection
        self.process = process

    async def read(self) -> bytes:
        return await self.process.stdout.read(16384)

    async def write(self, data: bytes) -> None:
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def resize(self, cols: int, rows: int) -> None:
        self.process.change_terminal_size(cols, rows)

    async def close(self) -> None:
        self.connection.close()
        await self.connection.wait_closed()


class SSHGateway:
    def __init__(self, profiles: ProfileService) -> None:
        self.profiles = profiles

    async def authorize(self, profile_id: str, actor: Actor) -> None:
        await self.profiles.authorize(profile_id, actor)

    async def candidate(self, profile_id: str) -> asyncssh.SSHKey:
        profile = await self.profiles.get(profile_id)
        address = await self.profiles.destination(profile)
        try:
            key = await asyncio.wait_for(
                asyncssh.get_server_host_key(address, profile.port, config=None), 10
            )
            if key is None:
                raise HTTPException(502, "SSH host key unavailable")
            return key
        except (OSError, asyncssh.Error, TimeoutError) as exc:
            raise HTTPException(502, "SSH host key retrieval failed") from exc

    async def open(self, profile_id: str, actor: Actor, cols: int, rows: int) -> SSHTransport:
        profile = await self.profiles.authorize(profile_id, actor)
        address = await self.profiles.destination(profile)
        key = await self.profiles.host_key(profile_id)
        if not key:
            raise HTTPException(409, "SSH host key approval required")
        secret = await self.profiles.credentials(profile)
        connection: asyncssh.SSHClientConnection | None = None
        try:
            public_key = asyncssh.import_public_key(key)
            connection = await asyncssh.connect(
                address,
                profile.port,
                username=profile.username,
                config=None,
                agent_path=None,
                client_keys=[asyncssh.import_private_key(secret)]
                if profile.auth_method == "key"
                else [],
                password=secret if profile.auth_method == "password" else None,
                known_hosts=([public_key], [], []),
                connect_timeout=10,
                login_timeout=10,
                keepalive_interval=15,
                keepalive_count_max=3,
                preferred_auth="publickey" if profile.auth_method == "key" else "password",
            )
            process = await asyncio.wait_for(
                connection.create_process(
                    term_type="xterm-256color",
                    term_size=(cols, rows),
                    encoding=None,
                    stderr=asyncssh.STDOUT,
                ),
                10,
            )
            return SSHTransport(connection, process)
        except (OSError, ValueError, asyncssh.Error, TimeoutError) as exc:
            if connection:
                connection.close()
                await connection.wait_closed()
            raise HTTPException(502, "SSH connection failed or host key rejected") from exc
        except BaseException:
            if connection:
                connection.close()
                await connection.wait_closed()
            raise
