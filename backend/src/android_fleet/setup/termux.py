"""Termux setup script and SSH verification anchored to authenticated ADB."""

import asyncio
import base64
import shlex
from contextlib import suppress

import asyncssh

from android_fleet.adb.base import AdbClient
from android_fleet.setup.catalog import SetupError


def setup_command(public_key: str, nonce: str) -> str:
    # Only a public key and a non-secret completion marker ever reach the screen.
    key = asyncssh.import_public_key(public_key).export_public_key().decode().strip()
    if len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
        raise ValueError("Invalid completion marker")
    script = f"""set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y -o Dpkg::Options::=--force-confold openssh
umask 077
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF {shlex.quote(key)} "$HOME/.ssh/authorized_keys" || \
    printf '%s\\n' {shlex.quote(key)} >> "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
ssh-keygen -A
cat > "$HOME/.ssh/fleet_sshd_config" <<EOF
Port 8022
ListenAddress 0.0.0.0
HostKey $PREFIX/etc/ssh/ssh_host_ed25519_key
AuthorizedKeysFile $HOME/.ssh/authorized_keys
PidFile $HOME/.ssh/fleet_sshd.pid
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
UsePAM no
EOF
sshd -t -f "$HOME/.ssh/fleet_sshd_config"
pkill -x sshd || true
sshd -f "$HOME/.ssh/fleet_sshd_config"
printf '%s\\n' {shlex.quote(nonce)} > "$HOME/.ssh/fleet_setup_complete"
printf '\\nSSH ready on port 8022. Password login is disabled.\\n'
"""
    payload = base64.b64encode(script.encode()).decode()
    # Android's `input text` uses %s to represent spaces. The script is encoded
    # to keep quotes, newlines, percent signs, and shell punctuation out of input.
    return f"echo%s{payload}|base64%s-d|bash"


class TermuxSSHVerifier:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

    async def verify(
        self,
        serial: str,
        host: str,
        username: str,
        private_key: str,
        nonce: str,
    ) -> asyncssh.SSHKey:
        port = await self.adb.forward_ssh(serial)
        try:
            async with asyncio.timeout(240):
                while True:
                    try:
                        # This tunnel belongs to the authenticated Android transport,
                        # so its host key is a device-bound trust anchor, not LAN TOFU.
                        key = await asyncio.wait_for(
                            asyncssh.get_server_host_key("127.0.0.1", port, config=None),
                            5,
                        )
                        if key is None:
                            raise OSError("Host key unavailable")
                        async with asyncssh.connect(
                            host,
                            8022,
                            username=username,
                            config=None,
                            agent_path=None,
                            client_keys=[asyncssh.import_private_key(private_key)],
                            known_hosts=([key], [], []),
                            preferred_auth="publickey",
                            connect_timeout=5,
                            login_timeout=5,
                        ) as connection:
                            result = await connection.run(
                                'cat "$HOME/.ssh/fleet_setup_complete"; id -un',
                                check=True,
                                timeout=5,
                            )
                            if str(result.stdout).splitlines() != [nonce, username]:
                                raise OSError("Setup not complete")
                            return key
                    except (OSError, asyncssh.Error, TimeoutError):
                        await asyncio.sleep(2)
        except TimeoutError as exc:
            raise SetupError(
                "SSH setup did not finish. Open Termux on the unlocked device, check its "
                "internet connection and package errors, then retry Enable Termux SSH."
            ) from exc
        finally:
            with suppress(OSError, RuntimeError, TimeoutError):
                await self.adb.remove_forward(serial, port)
