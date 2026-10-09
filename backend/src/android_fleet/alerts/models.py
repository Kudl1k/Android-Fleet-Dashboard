"""Validated, transport-independent alert configuration and lifecycle records."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Condition(StrEnum):
    BATTERY_LOW = "battery_low"
    BATTERY_TEMPERATURE = "battery_temperature"
    DEVICE_TEMPERATURE = "device_temperature"
    CPU_HIGH = "cpu_high"
    MEMORY_HIGH = "memory_high"
    STORAGE_LOW = "storage_low"
    OFFLINE = "offline"
    TELEMETRY_STALE = "telemetry_stale"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(StrEnum):
    PENDING = "pending"
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=120)
    condition: Condition
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    severity: Severity = Severity.WARNING
    threshold: float = Field(ge=0, le=86400)
    duration_seconds: float = Field(default=60, ge=0, le=86400)
    hysteresis: float = Field(default=0, ge=0, le=86400)
    enabled: bool = True

    @model_validator(mode="after")
    def bounds(self) -> "RuleInput":
        if self.condition in {
            Condition.BATTERY_LOW,
            Condition.CPU_HIGH,
            Condition.MEMORY_HIGH,
            Condition.STORAGE_LOW,
        }:
            if self.threshold > 1 or self.hysteresis > 1:
                raise ValueError("Ratio thresholds and hysteresis must be within 0..1")
            low = self.condition in {Condition.BATTERY_LOW, Condition.STORAGE_LOW}
            recovery = self.threshold + self.hysteresis if low else self.threshold - self.hysteresis
            if not 0 <= recovery <= 1:
                raise ValueError("Hysteresis recovery must be within 0..1")
        if self.condition in {Condition.OFFLINE, Condition.TELEMETRY_STALE}:
            if self.hysteresis > self.threshold:
                raise ValueError("Hysteresis must not exceed elapsed-time threshold")
        if self.condition in {Condition.BATTERY_TEMPERATURE, Condition.DEVICE_TEMPERATURE}:
            if self.threshold > 200 or self.hysteresis > 200:
                raise ValueError("Temperature thresholds must be within 0..200 Celsius")
        return self


class Rule(RuleInput):
    id: str


class Event(BaseModel):
    id: str
    rule_id: str
    device_id: str
    device_name: str
    condition: Condition
    severity: Severity
    threshold: float
    value: float | None
    state: AlertState
    started_at: datetime
    fired_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    updated_at: datetime


class EventPage(BaseModel):
    items: list[Event]
    total: int
    limit: int
    offset: int


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    condition: Condition | None = None
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    severity: Severity | None = None
    threshold: float | None = Field(default=None, ge=0, le=86400)
    duration_seconds: float | None = Field(default=None, ge=0, le=86400)
    hysteresis: float | None = Field(default=None, ge=0, le=86400)
    enabled: bool | None = None
