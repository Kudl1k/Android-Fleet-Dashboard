"""Stable JSON representations of current and historical normalized observations."""

from datetime import datetime

from pydantic import BaseModel, Field

from android_fleet.devices.models import Device, DeviceState
from android_fleet.metrics.catalog import DEFINITIONS, MetricKind, valid_metric
from android_fleet.metrics.models import HistoryPage, MetricSnapshot, MetricValue


class MetricResponse(BaseModel):
    name: str
    value: float
    unit: str
    kind: MetricKind
    labels: dict[str, str] = Field(default_factory=dict)


class CurrentMetricsResponse(BaseModel):
    device_id: str
    state: DeviceState
    observed_at: datetime | None
    stale: bool
    values: list[MetricResponse]


class HistoricalPointResponse(MetricResponse):
    observed_at: datetime


class HistoryResponse(BaseModel):
    device_id: str
    start: datetime
    end: datetime
    points: list[HistoricalPointResponse]
    next_cursor: str | None


def metric_response(value: MetricValue) -> MetricResponse:
    return MetricResponse(
        name=value.name,
        value=value.value,
        unit=value.unit,
        kind=DEFINITIONS[value.name].kind,
        labels=dict(value.labels),
    )


def current_response(
    device: Device, snapshot: MetricSnapshot | None, *, stale: bool = False
) -> CurrentMetricsResponse:
    available = snapshot is not None and snapshot.device_id == device.id
    return CurrentMetricsResponse(
        device_id=device.id,
        state=device.state,
        observed_at=snapshot.observed_at if snapshot is not None and available else None,
        stale=stale,
        values=[metric_response(value) for value in snapshot.values if valid_metric(value)]
        if snapshot is not None and available
        else [],
    )


def history_response(
    device_id: str, start: datetime, end: datetime, page: HistoryPage
) -> HistoryResponse:
    return HistoryResponse(
        device_id=device_id,
        start=start,
        end=end,
        points=[
            HistoricalPointResponse(
                **metric_response(point.metric).model_dump(), observed_at=point.observed_at
            )
            for point in page.points
        ],
        next_cursor=page.next_cursor,
    )
