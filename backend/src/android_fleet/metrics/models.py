from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    unit: str
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MetricSnapshot:
    device_id: str
    observed_at: datetime
    values: tuple[MetricValue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HistoricalPoint:
    observed_at: datetime
    metric: MetricValue


@dataclass(frozen=True)
class HistoryPage:
    points: tuple[HistoricalPoint, ...]
    next_cursor: str | None = None
