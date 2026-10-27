"""Package classification for app removal and phone cleanup.

Removal is deliberately conservative. A package is removable only when it is
installed by the user, or when it is a preinstalled app on the curated
REMOVABLE list. Everything else that ships with the system stays, and the
PROTECTED list can never be removed, even if it was installed by the user.

Preinstalled apps are removed with ``pm uninstall --user 0``: Android deletes
their data, cache and installed updates, while the factory APK stays on the
read-only system partition, so ``pm install-existing`` can restore them.
"""

import json
import re
from enum import StrEnum


class PackageCategory(StrEnum):
    PROTECTED = "protected"
    REMOVABLE = "removable"
    SYSTEM = "system"
    USER = "user"


# Needed by the project (ADB, SSH through Termux, root through Magisk) or by
# Android itself (UI, settings, telephony, Play services, WebView, input).
PROTECTED = frozenset(
    {
        "android",
        "com.android.shell",
        "com.android.systemui",
        "com.android.settings",
        "com.android.phone",
        "com.android.server.telecom",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.vending",
        "com.google.android.gms",
        "com.google.android.gsf",
        "com.google.android.webview",
        "com.android.webview",
        "com.google.android.trichromelibrary",
        "com.google.android.inputmethod.latin",
        "com.android.inputmethod.latin",
        "com.samsung.android.honeyboard",
        "com.google.android.apps.nexuslauncher",
        "com.android.launcher3",
        "com.sec.android.app.launcher",
        "com.google.android.ext.services",
        "com.google.android.ext.shared",
        "com.android.externalstorage",
        "com.android.documentsui",
        "com.google.android.documentsui",
        "com.android.location.fused",
        "com.android.keychain",
        "com.android.certinstaller",
        "com.android.bluetooth",
        "com.android.se",
        "com.android.mtp",
        "com.android.stk",
        "com.android.mms.service",
        "com.android.emergency",
        "com.android.dynsystem",
        "com.google.android.euicc",
        "com.google.android.setupwizard",
        "com.google.android.pixel.setupwizard",
        "com.google.android.tts",
        "com.termux",
        "com.termux.boot",
        "com.termux.api",
        "com.topjohnwu.magisk",
    }
)
PROTECTED_PREFIXES = (
    "com.android.providers.",
    "com.google.android.providers.",
    "com.android.networkstack",
    "com.google.android.networkstack",
    "com.android.cellbroadcast",
    "com.google.android.cellbroadcast",
    "com.android.server.",
    "com.android.service.ims",
    "com.android.ims",
    "com.google.android.ims",
    "org.codeaurora.",
    "com.qualcomm.",
    "com.qti.",
    "com.quicinc.",
    "vendor.qti.",
)
# Resource overlays carry no code and only break theming when removed.
PROTECTED_MARKERS = (".overlay", "auto_generated_rro", ".rro.", ".resources")
PLATFORM_PREFIXES = ("android.", "com.android.", "com.google.android.", "com.samsung.android.")

# Preinstalled apps the project does not need. They use storage and run in the
# background, which adds noise to benchmark runs.
REMOVABLE = frozenset(
    {
        # Google media and productivity apps
        "com.google.android.youtube",
        "com.google.android.apps.youtube.music",
        "com.google.android.music",
        "com.google.android.videos",
        "com.google.android.apps.photos",
        "com.google.android.apps.maps",
        "com.google.android.apps.docs",
        "com.google.android.apps.docs.editors.docs",
        "com.google.android.apps.docs.editors.sheets",
        "com.google.android.apps.docs.editors.slides",
        "com.google.android.gm",
        "com.google.android.calendar",
        "com.google.android.apps.tachyon",
        "com.google.android.apps.magazines",
        "com.google.android.apps.books",
        "com.google.android.apps.podcasts",
        "com.google.android.play.games",
        "com.google.android.apps.subscriptions.red",
        "com.google.android.apps.recorder",
        "com.google.android.apps.messaging",
        "com.google.android.googlequicksearchbox",
        "com.google.android.apps.googleassistant",
        "com.android.chrome",
        "com.google.android.GoogleCamera",
        "com.google.android.apps.nbu.files",
        # Pixel extras
        "com.google.android.apps.tips",
        "com.google.android.apps.wellbeing",
        "com.google.android.apps.wallpaper",
        "com.google.android.apps.safetyhub",
        "com.google.android.apps.scone",
        "com.google.android.apps.helprtc",
        "com.google.android.apps.gcs",
        "com.google.android.apps.restore",
        "com.google.android.apps.pixelmigrate",
        "com.google.android.apps.wearables.maestro.companion",
        "com.google.android.apps.internal.betterbug",
        "com.google.android.apps.diagnosticstool",
        "com.google.android.apps.carrier.log",
        "com.google.android.apps.carrier.carrierwifi",
        "com.google.android.apps.enterprise.dmagent",
        "com.google.android.apps.work.oobconfig",
        "com.google.android.hardwareinfo",
        "com.google.android.hiddenmenu",
        "com.google.android.feedback",
        "com.google.android.flipendo",
        "com.google.android.projection.gearhead",
        "com.google.android.marvin.talkback",
        "com.google.android.accessibility.soundamplifier",
        "com.google.audio.hearing.visualization.accessibility.scribe",
        "com.google.android.wfcactivation",
        "com.google.intelligence.sense",
        "com.google.ar.core",
        "com.google.vr.apps.ornament",
        "com.google.omadm.trigger",
        "android.autoinstalls.config.google.nexus",
        # AOSP extras
        "com.android.egg",
        "com.android.dreams.basic",
        "com.android.wallpaper.livepicker",
        "com.android.bookmarkprovider",
        "com.android.printspooler",
        "com.google.android.printservice.recommendation",
        "com.android.bips",
        "com.android.musicfx",
        "com.android.omadm.service",
        # Carrier (Verizon, Sprint, US Cellular)
        "com.verizon.mips.services",
        "com.verizon.obdm",
        "com.verizon.obdm_permissions",
        "com.verizon.services",
        "com.android.sdm.plugins.connmo",
        "com.android.sdm.plugins.dcmo",
        "com.android.sdm.plugins.diagmon",
        "com.android.sdm.plugins.sprintdm",
        "com.android.sdm.plugins.usccdm",
        # Samsung and partner apps
        "com.samsung.android.bixby.agent",
        "com.samsung.android.app.spage",
        "com.samsung.android.game.gamehome",
        "com.samsung.android.arzone",
        "com.samsung.android.aremoji",
        "com.samsung.android.app.tips",
        "com.samsung.android.tvplus",
        "com.samsung.android.kidsinstaller",
        "com.sec.android.app.sbrowser",
        "com.facebook.katana",
        "com.facebook.appmanager",
        "com.facebook.services",
        "com.facebook.system",
        "com.microsoft.skydrive",
        "com.microsoft.office.outlook",
        "com.linkedin.android",
        "com.netflix.mediaclient",
        "com.netflix.partner.activation",
        "com.spotify.music",
    }
)


def classify(package: str, system: bool) -> PackageCategory:
    if (
        package in PROTECTED
        or package.startswith(PROTECTED_PREFIXES)
        or any(marker in package for marker in PROTECTED_MARKERS)
    ):
        return PackageCategory.PROTECTED
    if package in REMOVABLE:
        return PackageCategory.REMOVABLE
    if system or package == "android" or package.startswith(PLATFORM_PREFIXES):
        return PackageCategory.SYSTEM
    return PackageCategory.USER


def removable(category: PackageCategory) -> bool:
    return category in {PackageCategory.REMOVABLE, PackageCategory.USER}


def parse_packages(output: str) -> set[str]:
    return {
        line.removeprefix("package:").strip()
        for line in output.splitlines()
        if line.startswith("package:") and line.removeprefix("package:").strip()
    }


def parse_diskstats(output: str) -> dict[str, int]:
    """Bytes used per package (code, data and cache) from ``dumpsys diskstats``.

    Android refreshes these numbers about once a day, so they are approximate
    and may be missing entirely on a freshly booted or unsupported device.
    """
    arrays: dict[str, list[object]] = {}
    for line in output.splitlines():
        match = re.match(r"(Package Names|App Sizes|App Data Sizes|Cache Sizes): (\[.*\])$", line)
        if match:
            try:
                value = json.loads(match.group(2))
            except ValueError:
                return {}
            if isinstance(value, list):
                arrays[match.group(1)] = value
    names = arrays.get("Package Names", [])
    sizes: dict[str, int] = {}
    for key in ("App Sizes", "App Data Sizes", "Cache Sizes"):
        values = arrays.get(key, [])
        if len(values) != len(names):
            continue
        for name, size in zip(names, values, strict=True):
            if isinstance(name, str) and isinstance(size, int) and size >= 0:
                sizes[name] = sizes.get(name, 0) + size
    return sizes
