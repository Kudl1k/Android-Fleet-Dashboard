"""Pinned official F-Droid artifacts, with bounded asynchronous downloads."""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx


class SetupError(RuntimeError):
    """A deliberately secret-free, user-actionable setup error."""


@dataclass(frozen=True)
class AppArtifact:
    package: str
    version: str
    size: int
    sha256: str
    filename: str


APPS = (
    AppArtifact(
        "org.fdroid.fdroid",
        "1.23.2",
        12426276,
        "985f5181d48bb6bafd54083a048b391271e0ab28385881cc41294fb01a222762",
        "org.fdroid.fdroid_1023052.apk",
    ),
    AppArtifact(
        "com.termux",
        "0.118.3",
        113880067,
        "e6265a57eb5ca363808488e3b01955958bed93bc0c8a0d281849b363b11027ec",
        "com.termux_1002.apk",
    ),
)
MAX_APK_BYTES = 128 * 1024 * 1024


class ApkDownloader:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def download(self, app: AppArtifact, path: Path) -> None:
        """No caller-selected URLs, redirects, unbounded responses, or partial artifacts."""
        digest = hashlib.sha256()
        size = 0
        try:
            async with (
                asyncio.timeout(180),
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=30,
                    follow_redirects=False,
                    headers={"Accept-Encoding": "identity"},
                    trust_env=False,
                ) as client,
            ):
                async with client.stream(
                    "GET", "https://f-droid.org/repo/" + app.filename
                ) as response:
                    response.raise_for_status()
                    if response.is_redirect:
                        raise SetupError("Official APK download redirected; retry later")
                    with path.open("wb") as output:
                        async for chunk in response.aiter_bytes(65536):
                            size += len(chunk)
                            if size > min(app.size, MAX_APK_BYTES):
                                raise SetupError("Official APK download exceeded its expected size")
                            digest.update(chunk)
                            output.write(chunk)
            if size != app.size or digest.hexdigest() != app.sha256:
                raise SetupError("Official APK checksum verification failed; nothing was installed")
        except (httpx.HTTPError, TimeoutError) as exc:
            raise SetupError(
                "Official APK download failed; check server internet access and retry"
            ) from exc
        except BaseException:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        finally:
            if size != app.size or digest.hexdigest() != app.sha256:
                await asyncio.to_thread(path.unlink, missing_ok=True)
