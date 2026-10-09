"""Legacy control guard retained for compatibility; never allow ambient loopback access."""

import secrets

from fastapi import Request

from android_fleet.core.settings import Settings


class ControlDenied(RuntimeError):
    pass


def require_control(request: Request, settings: Settings) -> None:
    actor = getattr(request.state, "actor", None)
    if actor is not None:
        if "device.manage" not in actor.permissions:
            raise ControlDenied("Device management permission is required")
        return
    if settings.control_token is None:
        raise ControlDenied("An authenticated control actor is required")
    authorization = request.headers.get("authorization", "")
    supplied = authorization.removeprefix("Bearer ")
    if not authorization.startswith("Bearer ") or not secrets.compare_digest(
        supplied.encode("utf-8"), settings.control_token.get_secret_value().encode("utf-8")
    ):
        raise ControlDenied("A valid control bearer token is required")
