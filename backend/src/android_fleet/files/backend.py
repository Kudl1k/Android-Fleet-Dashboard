"""Device file access behind one interface: ADB in production, memory in fake mode."""

import posixpath
import shlex
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from android_fleet.adb.base import AdbClient
from android_fleet.devices.models import Device
from android_fleet.execution.models import CommandResult
from android_fleet.files.paths import (
    STAGING_PREFIX,
    FileError,
    has_root,
    is_shared_storage,
    normalize,
)

PREVIEW_BYTES = 256 * 1024
LIST_LIMIT = 5000
# Exit codes the shell scripts use to report conditions the user can act on.
NOT_FOUND, WRONG_TYPE, DENIED, EXISTS = 3, 4, 5, 6
KINDS = {"d": "directory", "-": "file", "l": "symlink"}


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    kind: str
    size: int
    modified: float
    mode: str
    owner: str
    group: str


@dataclass(frozen=True)
class FilePreview:
    path: str
    size: int
    truncated: bool
    binary: bool
    content: str


class FileBackend(Protocol):
    async def listing(self, device: Device, path: str) -> list[FileEntry]: ...
    async def preview(self, device: Device, path: str) -> FilePreview: ...
    async def download(self, device: Device, path: str, local: Path, max_bytes: int) -> None: ...
    async def mkdir(self, device: Device, path: str) -> None: ...
    async def delete(self, device: Device, path: str) -> None: ...
    async def rename(self, device: Device, path: str, target: str) -> None: ...
    async def conflicts(self, device: Device, directory: str, names: list[str]) -> list[str]: ...
    async def install(
        self,
        device: Device,
        local: Path,
        directory: str,
        names: list[str],
        *,
        overwrite: bool,
        timeout: float,
    ) -> None: ...


def parse_listing(directory: str, output: str) -> list[FileEntry]:
    """Parse ``stat -c '%A|%s|%Y|%U|%G|%n'`` lines; the name is last so it may hold ``|``."""
    entries: list[FileEntry] = []
    for line in output.splitlines():
        fields = line.split("|", 5)
        if len(fields) != 6 or len(fields[0]) < 10:
            continue
        mode, size, modified, owner, group, name = fields
        if name in {".", "..", ""} or "/" in name:
            continue
        try:
            entry = FileEntry(
                name=name,
                path=posixpath.join(directory, name),
                kind=KINDS.get(mode[0], "other"),
                size=int(size),
                modified=float(modified),
                mode=mode,
                owner=owner,
                group=group,
            )
        except ValueError:
            continue
        entries.append(entry)
        if len(entries) >= LIST_LIMIT:
            break
    return sorted(entries, key=lambda e: (e.kind != "directory", e.name.lower()))


def ownership_fix(directory: str, names: list[str]) -> str:
    """Give new items the owner and SELinux label of the folder they were created in.

    Root creates files as root with a generic label; an app such as Termux could then
    neither read nor change them inside its own home.
    """
    targets = " ".join(shlex.quote(posixpath.join(directory, name)) for name in names)
    return (
        f"O=$(stat -c %u:%g -- {shlex.quote(directory)}) || exit {DENIED}\n"
        f'chown -R "$O" -- {targets} || exit {DENIED}\n'
        f"C=$(ls -dZ -- {shlex.quote(directory)} 2>/dev/null | cut -d' ' -f1)\n"
        f'case "$C" in u:*) chcon -R "$C" -- {targets} 2>/dev/null ;; esac\n'
    )


class AdbFileBackend:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

    async def _run(self, device: Device, script: str, timeout: float = 20) -> CommandResult:
        argv = ("su", "-c", script) if has_root(device) else ("sh", "-c", script)
        try:
            result = await self.adb.shell(device.serial, argv, timeout=timeout)
        except RuntimeError as exc:
            raise FileError("too_large", "The device returned too much output") from exc
        except (OSError, ValueError) as exc:
            raise FileError("device_error", "The device could not be reached") from exc
        if result.timeout:
            raise FileError("timeout", "The device did not answer in time")
        return result

    @staticmethod
    def _fail(result: CommandResult, messages: dict[int, tuple[str, str]]) -> None:
        if result.exit_code == 0:
            return
        if result.exit_code is not None and result.exit_code in messages:
            raise FileError(*messages[result.exit_code])
        if "ermission denied" in result.stderr or "ermission denied" in result.stdout:
            raise FileError("permission_denied", "Android denied access to this location")
        raise FileError("device_error", "The device rejected the file operation")

    async def listing(self, device: Device, path: str) -> list[FileEntry]:
        path = normalize(path)
        q = shlex.quote(path)
        script = (
            f"[ -e {q} ] || exit {NOT_FOUND}\n"
            f"[ -d {q} ] || exit {WRONG_TYPE}\n"
            f"cd -- {q} 2>/dev/null || exit {DENIED}\n"
            # Unmatched globs stay literal and stat reports them on the discarded stderr.
            "stat -c '%A|%s|%Y|%U|%G|%n' -- * .[!.]* ..?* 2>/dev/null\n"
            "exit 0\n"
        )
        result = await self._run(device, script)
        self._fail(
            result,
            {
                NOT_FOUND: ("not_found", "This folder does not exist"),
                WRONG_TYPE: ("not_directory", "This path is not a folder"),
                DENIED: ("permission_denied", "Android denied access to this folder"),
            },
        )
        return parse_listing(path, result.stdout)

    async def preview(self, device: Device, path: str) -> FilePreview:
        path = normalize(path)
        q = shlex.quote(path)
        script = (
            f"[ -e {q} ] || exit {NOT_FOUND}\n"
            f"[ -f {q} ] || exit {WRONG_TYPE}\n"
            f"[ -r {q} ] || exit {DENIED}\n"
            f"stat -c %s -- {q} || exit {DENIED}\n"
            f"head -c {PREVIEW_BYTES} -- {q}\n"
        )
        result = await self._run(device, script)
        self._fail(
            result,
            {
                NOT_FOUND: ("not_found", "This file does not exist"),
                WRONG_TYPE: ("not_file", "Only regular files can be previewed"),
                DENIED: ("permission_denied", "Android denied access to this file"),
            },
        )
        size_line, _, content = result.stdout.partition("\n")
        try:
            size = int(size_line)
        except ValueError as exc:
            raise FileError("device_error", "The device returned an unexpected answer") from exc
        binary = "\0" in content
        return FilePreview(
            path=path,
            size=size,
            truncated=size > PREVIEW_BYTES,
            binary=binary,
            content="" if binary else content,
        )

    async def download(self, device: Device, path: str, local: Path, max_bytes: int) -> None:
        path = normalize(path)
        q = shlex.quote(path)
        result = await self._run(
            device,
            f"[ -e {q} ] || exit {NOT_FOUND}\n[ -f {q} ] || exit {WRONG_TYPE}\n"
            f"stat -c %s -- {q} || exit {DENIED}\n",
        )
        self._fail(
            result,
            {
                NOT_FOUND: ("not_found", "This file does not exist"),
                WRONG_TYPE: ("not_file", "Only regular files can be downloaded"),
                DENIED: ("permission_denied", "Android denied access to this file"),
            },
        )
        try:
            size = int(result.stdout.strip())
        except ValueError as exc:
            raise FileError("device_error", "The device returned an unexpected answer") from exc
        if size > max_bytes:
            raise FileError(
                "too_large", f"Files over {max_bytes // 1048576} MiB cannot be downloaded"
            )
        timeout = 60 + size / 1_000_000
        if not has_root(device):
            await self._pull(device, path, local, timeout)
            return
        # adb pull runs as the shell user; root first copies the file somewhere it can read.
        staging = STAGING_PREFIX + uuid.uuid4().hex
        s = shlex.quote(staging)
        copy = await self._run(
            device,
            f"mkdir -m 755 {s} && cp -- {q} {s}/file && chmod 644 {s}/file || exit {DENIED}\n",
            timeout=timeout,
        )
        try:
            self._fail(copy, {DENIED: ("permission_denied", "The file could not be read")})
            await self._pull(device, staging + "/file", local, timeout)
        finally:
            await self._cleanup(device, staging)

    async def _cleanup(self, device: Device, staging: str) -> None:
        # Cleanup must never hide the error that ended the transfer.
        with suppress(FileError):
            await self._run(device, f"rm -rf -- {shlex.quote(staging)}")

    async def _pull(self, device: Device, remote: str, local: Path, timeout: float) -> None:
        try:
            await self.adb.pull(device.serial, remote, local, timeout=timeout)
        except TimeoutError as exc:
            raise FileError("timeout", "The transfer did not finish in time") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise FileError("device_error", "The file could not be transferred") from exc

    async def mkdir(self, device: Device, path: str) -> None:
        path = normalize(path)
        parent, name = posixpath.split(path)
        q = shlex.quote(path)
        fix = (
            ownership_fix(parent, [name])
            if has_root(device) and not is_shared_storage(path)
            else ""
        )
        script = (
            f"[ -e {q} ] && exit {EXISTS}\n"
            f"[ -d {shlex.quote(parent)} ] || exit {NOT_FOUND}\n"
            f"mkdir -- {q} || exit {DENIED}\n{fix}"
        )
        self._fail(
            await self._run(device, script),
            {
                EXISTS: ("exists", "A file or folder with this name already exists"),
                NOT_FOUND: ("not_found", "The parent folder does not exist"),
                DENIED: ("permission_denied", "Android denied creating the folder"),
            },
        )

    async def delete(self, device: Device, path: str) -> None:
        q = shlex.quote(normalize(path))
        script = f"[ -e {q} ] || [ -L {q} ] || exit {NOT_FOUND}\nrm -rf -- {q} || exit {DENIED}\n"
        self._fail(
            await self._run(device, script, timeout=120),
            {
                NOT_FOUND: ("not_found", "This item no longer exists"),
                DENIED: ("permission_denied", "Android denied removing this item"),
            },
        )

    async def rename(self, device: Device, path: str, target: str) -> None:
        q, t = shlex.quote(normalize(path)), shlex.quote(normalize(target))
        script = (
            f"[ -e {q} ] || [ -L {q} ] || exit {NOT_FOUND}\n"
            f"[ -e {t} ] && exit {EXISTS}\n"
            f"mv -- {q} {t} || exit {DENIED}\n"
        )
        self._fail(
            await self._run(device, script),
            {
                NOT_FOUND: ("not_found", "This item no longer exists"),
                EXISTS: ("exists", "An item with the new name already exists"),
                DENIED: ("permission_denied", "Android denied renaming this item"),
            },
        )

    async def conflicts(self, device: Device, directory: str, names: list[str]) -> list[str]:
        if not names:
            return []
        directory = normalize(directory)
        quoted = " ".join(shlex.quote(name) for name in names)
        script = (
            f"cd -- {shlex.quote(directory)} 2>/dev/null || exit 0\n"
            f'for n in {quoted}; do if [ -e "$n" ] || [ -L "$n" ]; then echo "$n"; fi; done\n'
        )
        result = await self._run(device, script)
        self._fail(result, {})
        found = set(result.stdout.splitlines())
        return [name for name in names if name in found]

    async def install(
        self,
        device: Device,
        local: Path,
        directory: str,
        names: list[str],
        *,
        overwrite: bool,
        timeout: float,
    ) -> None:
        directory = normalize(directory)
        staging = STAGING_PREFIX + uuid.uuid4().hex
        d = shlex.quote(directory)
        try:
            try:
                await self.adb.push_tree(device.serial, local, staging, timeout=timeout)
            except TimeoutError as exc:
                raise FileError("timeout", "The transfer did not finish in time") from exc
            except (OSError, RuntimeError, ValueError) as exc:
                raise FileError("device_error", "The files could not be transferred") from exc
            copies = []
            for name in names:
                source, target = (
                    shlex.quote(f"{staging}/{name}"),
                    shlex.quote(f"{directory}/{name}"),
                )
                replace = (
                    f"rm -rf -- {target} || exit {DENIED}\n"
                    if overwrite
                    else f"if [ -e {target} ] || [ -L {target} ]; then exit {EXISTS}; fi\n"
                )
                copies.append(f"{replace}cp -R -- {source} {target} || exit {DENIED}\n")
            fix = (
                ownership_fix(directory, names)
                if has_root(device) and not is_shared_storage(directory)
                else ""
            )
            # Owners must be able to change what they received, e.g. edit a copied script.
            modes = " ".join(shlex.quote(f"{directory}/{name}") for name in names)
            script = (
                f"mkdir -p -- {d} || exit {DENIED}\n"
                f"[ -d {d} ] || exit {NOT_FOUND}\n"
                + "".join(copies)
                + fix
                + f"chmod -R u+rwX -- {modes} 2>/dev/null\nexit 0\n"
            )
            self._fail(
                await self._run(device, script, timeout=timeout),
                {
                    EXISTS: ("exists", "An item with the same name already exists"),
                    NOT_FOUND: ("not_directory", "The destination is not a folder"),
                    DENIED: ("permission_denied", "Android denied writing to the destination"),
                },
            )
        finally:
            await self._cleanup(device, staging)
