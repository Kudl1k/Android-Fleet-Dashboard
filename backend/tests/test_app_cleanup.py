from pathlib import Path
from types import SimpleNamespace

import pytest
from test_control import Fleet, wait

from android_fleet.adb.fake import FakeAdbClient
from android_fleet.control.manager import Manager
from android_fleet.control.packages import (
    PackageCategory,
    classify,
    parse_diskstats,
    parse_packages,
)
from android_fleet.core.settings import Settings
from android_fleet.execution.models import CommandResult

YOUTUBE = "com.google.android.youtube"
MAPS = "com.google.android.apps.maps"
PHOTOS = "com.google.android.apps.photos"
SETTINGS = "com.android.settings"
TERMUX = "com.termux"
FDROID = "org.fdroid.fdroid"
VENDOR = "com.example.vendor.service"
DISKSTATS = f"""Latest 4096 bytes
Data-Free: 1000K / 2000K total = 50% free
Package Names: ["{YOUTUBE}","{MAPS}","{FDROID}"]
App Sizes: [100,200,300]
App Data Sizes: [10,20,30]
Cache Sizes: [1,2,3]
"""


class Phone(FakeAdbClient):
    """A stock phone with preinstalled apps, one user app and one removed app."""

    def __init__(self) -> None:
        super().__init__()
        self.installed = {YOUTUBE, MAPS, SETTINGS, TERMUX, FDROID, VENDOR}
        self.system = {YOUTUBE, MAPS, SETTINGS, VENDOR}
        self.removed = {PHOTOS}
        self.rejected: set[str] = set()

    async def shell(
        self, serial: str, argv: tuple[str, ...], *, timeout: float = 10.0
    ) -> CommandResult:
        listing = {
            ("pm", "list", "packages"): self.installed,
            ("pm", "list", "packages", "-s"): self.system,
            ("pm", "list", "packages", "-u"): self.installed | self.removed,
        }
        if argv in listing:
            self.calls.append((serial, argv))
            return CommandResult(
                stdout="".join(f"package:{name}\n" for name in sorted(listing[argv]))
            )
        if argv == ("dumpsys", "diskstats"):
            self.calls.append((serial, argv))
            return CommandResult(stdout=DISKSTATS)
        if argv[:4] == ("pm", "uninstall", "--user", "0"):
            self.calls.append((serial, argv))
            if argv[4] in self.rejected:
                return CommandResult(stdout="Failure [DELETE_FAILED_INTERNAL_ERROR]\n")
            self.installed.discard(argv[4])
            self.removed.add(argv[4])
            return CommandResult(stdout="Success\n")
        if argv[:2] == ("pm", "install-existing"):
            self.calls.append((serial, argv))
            self.removed.discard(argv[2])
            self.installed.add(argv[2])
            return CommandResult(stdout=f"Package {argv[2]} installed for user: 0\n")
        return await super().shell(serial, argv, timeout=timeout)


async def make_manager(tmp_path: Path) -> Manager:
    manager = Manager(Phone(), Fleet(), Settings(), tmp_path / "operations.db")  # type: ignore[arg-type]
    await manager.initialize()
    return manager


def calls(manager: Manager) -> list[tuple[str, ...]]:
    return [argv for _, argv in manager.client.calls]  # type: ignore[attr-defined]


ADMIN = SimpleNamespace(identity="admin", role="administrator")


@pytest.mark.parametrize(
    "package,system,category",
    [
        (YOUTUBE, True, PackageCategory.REMOVABLE),
        (SETTINGS, True, PackageCategory.PROTECTED),
        (TERMUX, False, PackageCategory.PROTECTED),
        ("com.topjohnwu.magisk", False, PackageCategory.PROTECTED),
        ("com.android.providers.media", True, PackageCategory.PROTECTED),
        ("com.qualcomm.qti.telephonyservice", True, PackageCategory.PROTECTED),
        ("com.android.phone.auto_generated_rro_vendor__", True, PackageCategory.PROTECTED),
        ("com.android.systemui.overlay.pixel", True, PackageCategory.PROTECTED),
        (VENDOR, True, PackageCategory.SYSTEM),
        ("com.android.traceur", False, PackageCategory.SYSTEM),
        (FDROID, False, PackageCategory.USER),
    ],
)
def test_classify(package: str, system: bool, category: PackageCategory) -> None:
    assert classify(package, system) is category


def test_parse_packages_ignores_noise() -> None:
    assert parse_packages("package:a.b\nWARNING: x\npackage:\npackage:c.d\n") == {"a.b", "c.d"}


def test_parse_diskstats() -> None:
    assert parse_diskstats(DISKSTATS) == {YOUTUBE: 111, MAPS: 222, FDROID: 333}
    assert parse_diskstats("Package Names: [broken\n") == {}
    assert parse_diskstats('Package Names: ["a"]\nApp Sizes: [1,2]\n') == {}
    assert parse_diskstats("") == {}


async def test_list_classifies_and_reports_removed(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    op = await manager.submit("device", "apps.list", ADMIN)
    result = (await wait(manager, op))["result"]
    apps = {app["package"]: app for app in result["apps"]}
    assert apps[YOUTUBE] == {
        "package": YOUTUBE,
        "system": True,
        "category": "removable",
        "size_bytes": 111,
    }
    assert apps[SETTINGS]["category"] == "protected"
    assert apps[VENDOR]["category"] == "system"
    assert apps[VENDOR]["size_bytes"] is None
    assert apps[FDROID]["category"] == "user"
    assert result["removed"] == [PHOTOS]
    assert YOUTUBE in result["packages"]
    await manager.close()


async def test_uninstall_preinstalled_app_for_user(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    op = await manager.submit("device", "apps.uninstall", ADMIN, package=YOUTUBE, confirmed=True)
    assert (await wait(manager, op))["state"] == "succeeded"
    assert ("pm", "uninstall", "--user", "0", YOUTUBE) in calls(manager)
    assert not any(argv[0] == "uninstall" for argv in calls(manager))
    await manager.close()


async def test_uninstall_user_app_completely(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    op = await manager.submit("device", "apps.uninstall", ADMIN, package=FDROID, confirmed=True)
    assert (await wait(manager, op))["state"] == "succeeded"
    assert ("uninstall", FDROID) in calls(manager)
    await manager.close()


@pytest.mark.parametrize("package", [TERMUX, SETTINGS, VENDOR])
async def test_protected_and_unlisted_system_apps_are_kept(tmp_path: Path, package: str) -> None:
    manager = await make_manager(tmp_path)
    op = await manager.submit("device", "apps.uninstall", ADMIN, package=package, confirmed=True)
    final = await wait(manager, op)
    assert final["state"] == "failed"
    assert final["error"] == "Protected/system packages cannot be uninstalled"
    assert not any("uninstall" in argv for argv in calls(manager))
    await manager.close()


async def test_restore_only_removed_apps(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    op = await manager.submit("device", "apps.restore", ADMIN, package=PHOTOS)
    assert (await wait(manager, op))["state"] == "succeeded"
    assert ("pm", "install-existing", PHOTOS) in calls(manager)
    op = await manager.submit("device", "apps.restore", ADMIN, package=MAPS)
    final = await wait(manager, op)
    assert final["state"] == "failed"
    assert final["error"] == "Only removed preinstalled apps can be restored"
    assert ("pm", "install-existing", MAPS) not in calls(manager)
    await manager.close()


async def test_cleanup_removes_only_curated_apps(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    manager.client.rejected.add(MAPS)  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        await manager.submit("device", "apps.cleanup", ADMIN)
    op = await manager.submit("device", "apps.cleanup", ADMIN, confirmed=True)
    final = await wait(manager, op)
    assert final["state"] == "succeeded"
    assert final["result"] == {
        "removed": [YOUTUBE],
        "failed": [MAPS],
        "freed_bytes_estimate": 111,
    }
    removals = [argv[-1] for argv in calls(manager) if "uninstall" in argv]
    assert sorted(removals) == [MAPS, YOUTUBE]
    await manager.close()
