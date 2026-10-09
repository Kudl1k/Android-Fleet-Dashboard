"""Acceptance utility validation without hardware or screenshot artifacts."""

import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "safe_acceptance", Path(__file__).parents[2] / "scripts/m4_safe_acceptance.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def chunk(kind: bytes, content: bytes) -> bytes:
    return (
        struct.pack(">I", len(content))
        + kind
        + content
        + struct.pack(">I", zlib.crc32(kind + content))
    )


def png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
        + chunk(b"IEND", b"")
    )


def test_png_framing() -> None:
    assert module.validate_png(png()) == (1, 1)


@pytest.mark.parametrize("data", [b"not image", png()[:-1], png() + b"extra", png()[:40] + b"bad"])
def test_reject_corrupt_image(data: bytes) -> None:
    with pytest.raises(ValueError):
        module.validate_png(data)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:9000",
        "http://example.com",
        "http://127.0.0.1@evil.com",
        "http://localhost/path",
        "http://localhost?token=x",
    ],
)
def test_reject_external_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError):
        module.Client(url, "fixture-token")


def test_allowlist_contains_only_approved_actions() -> None:
    assert module.ACTIONS == ("state", "properties", "apps.list", "screenshot")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_reject_unbounded_deadlines(timeout: float) -> None:
    with pytest.raises(ValueError):
        module.run(None, "fixture-device", timeout)


@pytest.mark.parametrize("token", ["", " ", "bad\ntoken", " spaced"])
def test_reject_invalid_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        module.Client("http://127.0.0.1:9000", token)


def test_waits_for_async_audit_append(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        audit_reads = 0

        def json(self, path: str, body: dict[str, str] | None = None) -> dict:
            if path.endswith("/auth/me"):
                return {"role": "administrator"}
            if body:
                return {"id": "fixture-op", "state": "succeeded"}
            if path.startswith("/api/v1/operations?"):
                return {"items": [{"id": "fixture-op"}]}
            self.audit_reads += 1
            if self.audit_reads == 1:
                return {"items": []}
            return {"items": [{"request_id": "fixture-op", "outcome": "succeeded"}]}

    client = FakeClient()
    monkeypatch.setattr(module, "ACTIONS", ("state",))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    evidence = module.run(client, "fixture-device", 1)
    assert client.audit_reads == 2
    assert evidence["state"]["audit_verified"] is True
