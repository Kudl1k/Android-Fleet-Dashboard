"""Safe, explicit-device REST acceptance; never print tokens or screenshot contents."""

import argparse
import json
import math
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

ACTIONS = ("state", "properties", "apps.list", "screenshot")
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def validate_png(data: bytes) -> tuple[int, int]:
    """Check bounded PNG framing and CRCs without rendering private pixels."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 16 * 1024 * 1024:
        raise ValueError("Invalid or oversized PNG")
    offset = 8
    dimensions = None
    seen_idat = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG")
        content = data[offset + 8 : end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + content) != crc:
            raise ValueError("Invalid PNG checksum")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Missing PNG header")
            dimensions = struct.unpack_from(">II", content)
            if not all(0 < value <= 32768 for value in dimensions):
                raise ValueError("Invalid PNG dimensions")
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            if length or end != len(data) or not seen_idat:
                raise ValueError("Invalid PNG end")
            return dimensions
        offset = end
    raise ValueError("Missing PNG end")


class Client:
    def __init__(self, base: str, token: str) -> None:
        if not token.strip() or any(character.isspace() for character in token):
            raise ValueError("Invalid authentication token")
        parsed = urllib.parse.urlsplit(base)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Only local HTTP backend URLs are permitted")
        self.base = base.rstrip("/")
        self.token = token

        # Avoid proxy forwarding and redirects that could disclose credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(
        self,
        path: str,
        body: dict[str, str] | None = None,
        *,
        authenticated: bool = True,
    ) -> tuple[int, bytes]:
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError("Response exceeds acceptance limit")
                return response.status, data
        except urllib.error.HTTPError as exc:
            return exc.code, b""  # Never echo possibly sensitive backend errors.
        except urllib.error.URLError as exc:
            raise ConnectionError("Local backend unreachable") from exc

    def json(self, path: str, body: dict[str, str] | None = None) -> Any:
        status, data = self.request(path, body)
        if not 200 <= status < 300:
            raise ValueError(f"HTTP {status}")
        return json.loads(data)


def run(client: Client, device_id: str, timeout: float) -> dict[str, Any]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive")
    if not device_id.strip():
        raise ValueError("Explicit device identifier required")
    actor = client.json("/api/v1/auth/me")
    if actor.get("role") != "administrator":
        raise ValueError("Administrator identity required for audit acceptance")
    device = urllib.parse.quote(device_id, safe="")
    evidence: dict[str, Any] = {}
    for action in ACTIONS:
        op = client.json(f"/api/v1/devices/{device}/operations", {"action": action})
        operation_id = urllib.parse.quote(op["id"], safe="")
        transitions = [op["state"]]
        deadline = time.monotonic() + timeout
        while op["state"] not in TERMINAL:
            if time.monotonic() >= deadline:
                raise TimeoutError("Acceptance polling deadline exceeded")
            time.sleep(0.25)
            op = client.json(f"/api/v1/operations/{operation_id}")
            if op["state"] != transitions[-1]:
                transitions.append(op["state"])
        if op["state"] != "succeeded":
            raise ValueError(f"Safe action {action} ended {op['state']}")
        history = client.json(
            "/api/v1/operations?"
            + urllib.parse.urlencode({"device_id": device_id, "action": action, "limit": 200})
        )
        if not any(item["id"] == op["id"] for item in history["items"]):
            raise ValueError("Operation missing from history")
        audit_path = "/api/v1/audit?" + urllib.parse.urlencode(
            {"device_id": device_id, "action": action, "limit": 200}
        )
        while True:
            audit = client.json(audit_path)
            matching = [item for item in audit["items"] if item["request_id"] == op["id"]]
            if any(item["outcome"] == "succeeded" for item in matching):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Successful operation audit deadline exceeded")
            time.sleep(0.25)
        evidence[action] = {
            "status": "PASS",
            "observed_states": transitions,
            "history_verified": True,
            "audit_verified": True,
        }
        if action == "screenshot":
            path = f"/api/v1/operations/{operation_id}/screenshot"
            status, data = client.request(path)
            if status != 200:
                raise ValueError("Screenshot download failed")
            width, height = validate_png(data)
            denied, _ = client.request(path, authenticated=False)
            if denied not in {401, 403}:
                raise ValueError("Unauthenticated screenshot was not rejected")
            evidence[action].update(
                width=width, height=height, bytes=len(data), unauthorized_status=denied
            )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    token = os.environ.get("M4_ACCEPTANCE_TOKEN", "")
    if not token.strip():
        print(json.dumps({"status": "BLOCKED", "reason": "M4_ACCEPTANCE_TOKEN missing"}))
        return 2
    try:
        evidence = run(Client(args.base_url, token), args.device_id, args.timeout)
    except (ValueError, KeyError, TimeoutError, ConnectionError) as exc:
        # Fixed failure category, never exception text or response payloads.
        print(
            json.dumps(
                {
                    "status": "BLOCKED" if isinstance(exc, ConnectionError) else "FAIL",
                    "reason": type(exc).__name__,
                }
            )
        )
        return 1
    print(json.dumps({"status": "PASS", "checks": evidence}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
