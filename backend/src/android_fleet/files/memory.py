"""In-memory device file systems for fake ADB mode and tests."""

import asyncio
import posixpath
import time
from dataclasses import dataclass, field
from pathlib import Path

from android_fleet.devices.models import Device
from android_fleet.files.backend import PREVIEW_BYTES, FileEntry, FilePreview
from android_fleet.files.paths import TERMUX_HOME, FileError, has_root, normalize


@dataclass
class Node:
    directory: bool
    data: bytes = b""
    modified: float = field(default_factory=time.time)
    protected: bool = False


SEED = {
    "/sdcard/Download/notes.txt": b"Fake device notes\n",
    "/sdcard/Documents/": b"",
    "/data/local/tmp/": b"",
    TERMUX_HOME + "/hello.py": b"print('hello from the fake device')\n",
}
# Readable only with root, as Android hides app data from the shell user.
PRIVATE = ("/data/data",)


class MemoryFileBackend:
    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Node]] = {}

    def _tree(self, device: Device) -> dict[str, Node]:
        if device.id not in self.devices:
            tree = {"/": Node(True, protected=True)}
            for path, data in SEED.items():
                directory = path.endswith("/")
                path = path.rstrip("/")
                self._parents(tree, path)
                tree[path] = Node(directory, data)
            tree["/sdcard"].protected = True
            self.devices[device.id] = tree
        return self.devices[device.id]

    @staticmethod
    def _parents(tree: dict[str, Node], path: str) -> None:
        parent = posixpath.dirname(path)
        while parent not in tree:
            tree[parent] = Node(True)
            parent = posixpath.dirname(parent)

    def _visible(self, device: Device, path: str) -> None:
        if not has_root(device) and any(path == p or path.startswith(p + "/") for p in PRIVATE):
            raise FileError("permission_denied", "Android denied access to this location")

    def _node(self, device: Device, path: str) -> Node:
        self._visible(device, path)
        node = self._tree(device).get(path)
        if node is None:
            raise FileError("not_found", "This item does not exist")
        return node

    async def listing(self, device: Device, path: str) -> list[FileEntry]:
        path = normalize(path)
        if not self._node(device, path).directory:
            raise FileError("not_directory", "This path is not a folder")
        entries = [
            FileEntry(
                name=posixpath.basename(child),
                path=child,
                kind="directory" if node.directory else "file",
                size=4096 if node.directory else len(node.data),
                modified=node.modified,
                mode="drwxrwx---" if node.directory else "-rw-rw----",
                owner="shell",
                group="shell",
            )
            for child, node in self._tree(device).items()
            if child != path and posixpath.dirname(child) == path
        ]
        return sorted(entries, key=lambda e: (e.kind != "directory", e.name.lower()))

    async def preview(self, device: Device, path: str) -> FilePreview:
        path = normalize(path)
        node = self._node(device, path)
        if node.directory:
            raise FileError("not_file", "Only regular files can be previewed")
        binary = b"\0" in node.data[:PREVIEW_BYTES]
        return FilePreview(
            path=path,
            size=len(node.data),
            truncated=len(node.data) > PREVIEW_BYTES,
            binary=binary,
            content="" if binary else node.data[:PREVIEW_BYTES].decode(errors="replace"),
        )

    async def download(self, device: Device, path: str, local: Path, max_bytes: int) -> None:
        node = self._node(device, normalize(path))
        if node.directory:
            raise FileError("not_file", "Only regular files can be downloaded")
        if len(node.data) > max_bytes:
            raise FileError("too_large", "This file is too large to download")
        await asyncio.to_thread(local.write_bytes, node.data)

    async def mkdir(self, device: Device, path: str) -> None:
        path = normalize(path)
        tree = self._tree(device)
        if path in tree:
            raise FileError("exists", "A file or folder with this name already exists")
        if not self._node(device, posixpath.dirname(path)).directory:
            raise FileError("not_found", "The parent folder does not exist")
        tree[path] = Node(True)

    async def delete(self, device: Device, path: str) -> None:
        path = normalize(path)
        if self._node(device, path).protected:
            raise FileError("permission_denied", "Android denied removing this item")
        tree = self._tree(device)
        for child in [p for p in tree if p == path or p.startswith(path + "/")]:
            del tree[child]

    async def rename(self, device: Device, path: str, target: str) -> None:
        path, target = normalize(path), normalize(target)
        self._node(device, path)
        tree = self._tree(device)
        if target in tree:
            raise FileError("exists", "An item with the new name already exists")
        for child in [p for p in tree if p == path or p.startswith(path + "/")]:
            tree[target + child[len(path) :]] = tree.pop(child)

    async def conflicts(self, device: Device, directory: str, names: list[str]) -> list[str]:
        tree = self._tree(device)
        directory = normalize(directory)
        return [n for n in names if posixpath.join(directory, n) in tree]

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
        self._visible(device, directory)
        tree = self._tree(device)
        if directory in tree and not tree[directory].directory:
            raise FileError("not_directory", "The destination is not a folder")
        if not overwrite and await self.conflicts(device, directory, names):
            raise FileError("exists", "An item with the same name already exists")
        self._parents(tree, directory + "/x")
        tree.setdefault(directory, Node(True))
        for name in names:
            target = posixpath.join(directory, name)
            for child in [p for p in tree if p == target or p.startswith(target + "/")]:
                del tree[child]
            source = local / name
            for item in [source, *sorted(source.rglob("*"))]:
                relative = item.relative_to(local).as_posix()
                tree[posixpath.join(directory, relative)] = Node(
                    item.is_dir(), b"" if item.is_dir() else item.read_bytes()
                )
