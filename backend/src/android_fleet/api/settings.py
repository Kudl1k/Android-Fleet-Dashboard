"""Runtime settings API: read for viewers, change for device managers, always audited."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from android_fleet.core.runtime_settings import InvalidSetting, RuntimeSettings
from android_fleet.devices.registry import DeviceNotFound
from android_fleet.devices.service import FleetService
from android_fleet.security import SecurityService


class SettingsChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, float | None]


def settings_router(
    runtime: RuntimeSettings, fleet: FleetService, security: SecurityService
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def payload() -> dict[str, Any]:
        return {"settings": runtime.describe(), "devices": runtime.device_overrides()}

    @router.get("/settings")
    async def read(request: Request) -> dict[str, Any]:
        await security.authorize(request, "device.read")
        return payload()

    @router.put("/settings")
    async def change(body: SettingsChange, request: Request) -> dict[str, Any]:
        actor = await security.authorize(request, "device.manage")
        try:
            await runtime.update(body.values, actor.identity)
        except InvalidSetting as error:
            raise HTTPException(422, str(error)) from error
        await security.audit(
            actor,
            None,
            "settings.update",
            getattr(request.state, "request_id", str(uuid.uuid4())),
            "allowed",
            "succeeded",
        )
        return payload()

    @router.put("/settings/devices/{device_id}")
    async def change_device(
        device_id: str, body: SettingsChange, request: Request
    ) -> dict[str, Any]:
        actor = await security.authorize(request, "device.manage")
        try:
            fleet.get(device_id)
        except DeviceNotFound as error:
            raise HTTPException(404, "Device not found") from error
        try:
            await runtime.update_device(device_id, body.values, actor.identity)
        except InvalidSetting as error:
            raise HTTPException(422, str(error)) from error
        await security.audit(
            actor,
            device_id,
            "settings.device.update",
            getattr(request.state, "request_id", str(uuid.uuid4())),
            "allowed",
            "succeeded",
        )
        return payload()

    return router
