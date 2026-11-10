"""Path rules for the device file manager.

Browsing accepts any absolute path the device shell can read. Writing is limited to
locations meant for user data, so a mistyped path can never touch system partitions.
"""

import posixpath
from dataclasses import dataclass

from android_fleet.devices.models import Device, DeviceCapability

SHARED_STORAGE = ("/sdcard", "/storage/emulated/0", "/storage/self/primary")
DEVICE_TEMP = "/data/local/tmp"
TERMUX_HOME = "/data/data/com.termux/files/home"
# Staging for transfers in flight; the manager owns it, users never write there.
STAGING_PREFIX = "/data/local/tmp/fleet-files-"
MAX_PATH = 4096
MAX_NAME = 255


class FileError(Exception):
    """A file operation failed for a reason the user can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Location:
    label: str
    path: str
    writable: bool


def has_root(device: Device) -> bool:
    return DeviceCapability.ROOT_SHELL in device.capabilities


def normalize(path: str) -> str:
    """An absolute, normalized device path; rejects anything a shell could misread."""
    if (
        not path
        or not path.startswith("/")
        or len(path) > MAX_PATH
        or any(ch in path for ch in "\0\n\r")
    ):
        raise FileError("invalid_path", "Use an absolute device path")
    normalized = posixpath.normpath(path)
    # normpath keeps a leading "//"; POSIX allows it but it only confuses comparisons.
    return "/" + normalized.lstrip("/")


def validate_name(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or len(name.encode()) > MAX_NAME
        or any(ch in name for ch in "\0\n\r")
    ):
        raise FileError("invalid_name", "Use a single file or folder name without slashes")
    return name


def validate_relative(path: str) -> tuple[str, ...]:
    """Split an upload path such as ``final/input/a.jpg`` into checked parts."""
    parts = tuple(path.replace("\\", "/").split("/"))
    if not path or len(path) > MAX_PATH or path.startswith("/"):
        raise FileError("invalid_path", "Upload paths must be relative")
    return tuple(validate_name(part) for part in parts)


def writable_roots(device: Device) -> tuple[str, ...]:
    roots = (*SHARED_STORAGE, DEVICE_TEMP)
    # The Termux home belongs to the Termux app; only root can write into it.
    return (*roots, TERMUX_HOME) if has_root(device) else roots


def within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def ensure_writable(device: Device, path: str, *, allow_root: bool = False) -> str:
    """Return the normalized path when the device user area may be changed there."""
    path = normalize(path)
    if path.startswith(STAGING_PREFIX):
        raise FileError("read_only", "This folder is reserved for transfers in progress")
    for root in writable_roots(device):
        if within(path, root) and (allow_root or path != root):
            return path
    allowed = ", ".join(writable_roots(device))
    raise FileError("read_only", f"Changes are allowed only inside {allowed}")


def is_shared_storage(path: str) -> bool:
    return any(within(path, root) for root in SHARED_STORAGE)


def locations(device: Device) -> tuple[Location, ...]:
    places = [
        Location("Shared storage", "/sdcard", True),
        Location("Downloads", "/sdcard/Download", True),
        Location("Device temp", DEVICE_TEMP, True),
    ]
    if has_root(device):
        places.append(Location("Termux home", TERMUX_HOME, True))
    places.append(Location("Device root", "/", False))
    return tuple(places)
