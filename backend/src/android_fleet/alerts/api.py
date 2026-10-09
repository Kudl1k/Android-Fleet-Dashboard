"""Versioned monitoring reads and authenticated alert controls."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from android_fleet.alerts.engine import AlertEngine
from android_fleet.alerts.models import (
    AlertState,
    Event,
    EventPage,
    Rule,
    RuleInput,
    RulePatch,
    Severity,
)


def router(
    engine: AlertEngine, control: Callable[[Request], Coroutine[Any, Any, None]]
) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/alerts")

    @routes.get("/rules")
    async def rules() -> list[Rule]:
        return await engine.store.rules()

    @routes.post("/rules", status_code=201, dependencies=[Depends(control)])
    async def create_rule(body: RuleInput) -> Rule:
        try:
            return await engine.save_rule(body)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @routes.patch("/rules/{rule_id}", dependencies=[Depends(control)])
    async def patch_rule(rule_id: str, body: RulePatch) -> Rule:
        try:
            return await engine.patch_rule(rule_id, body)
        except ValueError as error:
            raise HTTPException(422, "Invalid alert rule") from error

    @routes.delete("/rules/{rule_id}", status_code=204, dependencies=[Depends(control)])
    async def delete_rule(rule_id: str) -> Response:
        await engine.delete_rule(rule_id)
        return Response(status_code=204)

    @routes.get("")
    async def events(
        state: AlertState | None = None,
        severity: Severity | None = None,
        device_id: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> EventPage:
        items, total = await engine.store.events(
            state=state, severity=severity, device_id=device_id, limit=limit, offset=offset
        )
        return EventPage(items=items, total=total, limit=limit, offset=offset)

    @routes.post("/{event_id}/acknowledge", dependencies=[Depends(control)])
    async def acknowledge(event_id: str) -> Event:
        try:
            return await engine.acknowledge(event_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    return routes
