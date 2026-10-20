"""Optional F-Droid/Termux preparation; fleet monitoring remains ADB-only."""

import asyncio
import re
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from android_fleet.adb.base import AdbClient
from android_fleet.control.manager import validate_apk
from android_fleet.devices.models import DeviceCapability, DeviceState
from android_fleet.devices.service import FleetService
from android_fleet.setup.catalog import APPS, MAX_APK_BYTES, ApkDownloader, SetupError
from android_fleet.setup.readiness import termux_has_focus
from android_fleet.setup.termux import TermuxSSHVerifier, setup_command
from android_fleet.terminal.profiles import ProfileService


class DeviceSetup:
    def __init__(
        self,
        adb: AdbClient,
        fleet: FleetService,
        profiles: ProfileService,
        artifacts: Path,
        downloader: ApkDownloader | None = None,
        verifier: TermuxSSHVerifier | None = None,
    ) -> None:
        self.adb = adb
        self.fleet = fleet
        self.profiles = profiles
        self.artifacts = artifacts
        self.downloader = downloader or ApkDownloader()
        self.verifier = verifier or TermuxSSHVerifier(adb)

    async def run(
        self,
        device_id: str,
        action: str,
        progress: Callable[[str], None],
    ) -> dict[str, object]:
        device = self.fleet.get(device_id)
        if (
            device.state != DeviceState.ONLINE
            or DeviceCapability.ADB_SHELL not in device.capabilities
        ):
            raise SetupError("Connect and authorize the device before starting setup")
        if self.profiles.cipher is None:
            raise SetupError(
                "Configure ANDROID_FLEET_SSH_ENCRYPTION_KEY on the server before setup"
            )
        config = self.fleet.configs[device_id]
        if not config.host:
            raise SetupError("Register a private network address for this device before SSH setup")
        serial = device.serial

        async def shell(argv: tuple[str, ...], timeout: float = 10) -> str:
            result = await self.adb.shell(serial, argv, timeout=timeout)
            if result.timeout:
                raise SetupError("Device command timed out; reconnect and retry setup")
            if result.exit_code != 0:
                raise SetupError("Android rejected setup; keep the device unlocked and retry")
            return result.stdout

        if (await shell(("am", "get-current-user"))).strip() != "0":
            raise SetupError(
                "Termux setup currently supports the device's primary Android user only"
            )
        # Validate the eventual SSH destination before installing or typing anything.
        self.profiles.validate_termux_host(config.host)
        if action == "setup.termux":
            for app in APPS:
                progress("Checking " + app.package)
                existing = await self.adb.shell(serial, ("pm", "path", app.package), timeout=10)
                if existing.timeout:
                    raise SetupError("Device package check timed out")
                if existing.exit_code == 0 and existing.stdout.startswith("package:"):
                    continue
                progress("Downloading and verifying " + app.package + " " + app.version)
                with tempfile.NamedTemporaryFile(
                    dir=self.artifacts, suffix=".apk", delete=False
                ) as file:
                    path = Path(file.name)
                try:
                    await self.downloader.download(app, path)
                    await asyncio.to_thread(validate_apk, path, MAX_APK_BYTES)
                    progress("Installing " + app.package)
                    result = await self.adb.command(serial, ("install", str(path)), timeout=120)
                    if result.timeout or result.exit_code != 0 or "Success" not in result.stdout:
                        raise SetupError(
                            "Android rejected the APK installation. Check install restrictions and "
                            "existing app signatures; existing apps and data were not removed."
                        )
                    if not (await shell(("pm", "path", app.package))).startswith("package:"):
                        raise SetupError("Application installation could not be verified")
                finally:
                    await asyncio.to_thread(path.unlink, missing_ok=True)
        elif action != "setup.ssh":
            raise SetupError("Unknown setup action")
        if not (await shell(("pm", "path", "com.termux"))).startswith("package:"):
            raise SetupError("Install Termux before enabling SSH")
        uid_output = await shell(("pm", "list", "packages", "-U", "com.termux"))
        uid_match = re.search(r"^package:com\.termux uid:(\d+)$", uid_output, re.MULTILINE)
        if not uid_match:
            raise SetupError("Cannot determine the Termux user; SSH was not configured")
        uid = int(uid_match[1])
        if not 10000 <= uid < 100000:
            raise SetupError("Unsupported Termux Android user")
        username = f"u0_a{uid - 10000}"
        progress("Opening Termux; keep the device unlocked and allow initial setup to finish")
        await shell(("am", "start", "-n", "com.termux/com.termux.app.TermuxActivity"))

        async def focused() -> bool:
            # Samsung's "windows" subcommand omits the global focus fields.
            # Probe the display summary first, then the full dump on older builds.
            for argv in (("dumpsys", "window", "displays"), ("dumpsys", "window")):
                focus = termux_has_focus(await shell(argv))
                if focus is not None:
                    return focus
            return False

        try:
            async with asyncio.timeout(45):
                while True:
                    processes = await shell(("ps", "-A", "-o", "UID,NAME"))
                    ready = any(
                        len(fields := line.split()) == 2
                        and fields[0] == str(uid)
                        and fields[1].rsplit("/", 1)[-1] in {"bash", "login", "zsh", "fish"}
                        for line in processes.splitlines()
                    )
                    if ready and await focused():
                        break
                    await asyncio.sleep(1)
        except TimeoutError as exc:
            raise SetupError(
                "Open Termux on the unlocked device and wait for its shell prompt, "
                "then click Enable Termux SSH. No commands need to be typed."
            ) from exc
        try:
            profile = await self.profiles.prepare_termux(
                device_id, config.host, device.name, username
            )
            private_key = await self.profiles.credentials(profile)
            import asyncssh

            public_key = asyncssh.import_private_key(private_key).export_public_key().decode()
            nonce = secrets.token_hex(16)
            command = setup_command(public_key, nonce)
            progress("Configuring key-only SSH in Termux; leave its terminal in the foreground")
            if not await focused():
                raise SetupError("Termux lost focus; open its shell and retry Enable Termux SSH")
            # Long input bursts can overflow the terminal's input queue and lose
            # the end of the command. Pace bounded chunks before pressing Enter.
            text = command.replace("%s", " ")
            for offset in range(0, len(text), 64):
                if not await focused():
                    raise SetupError(
                        "Termux lost focus while typing; clear its input before retrying"
                    )
                chunk = text[offset : offset + 64].replace(" ", "%s")
                await shell(("input", "text", chunk), timeout=10)
                await asyncio.sleep(0.1)
            if not await focused():
                raise SetupError(
                    "Termux lost focus before execution; reopen its shell before retrying"
                )
            await shell(("input", "keyevent", "66"))
            progress("Installing OpenSSH and verifying authenticated login on port 8022")
            host_key = await self.verifier.verify(serial, config.host, username, private_key, nonce)
            await self.profiles.complete_termux(profile.id, host_key)
        except HTTPException as exc:
            raise SetupError(
                "SSH profile storage is unavailable; check the server SSH configuration"
            ) from exc
        return {
            "stage": "SSH login verified",
            "profile_id": profile.id,
            "host": config.host,
            "port": 8022,
            "username": username,
            "fingerprint": host_key.get_fingerprint("sha256"),
            "authentication": "Dashboard-managed SSH key; password login disabled",
        }
