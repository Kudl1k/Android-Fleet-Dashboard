from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", populate_by_name=True)

    fake_adb: bool = Field(default=True, validation_alias="ANDROID_FLEET_FAKE_ADB")
    adb_binary: str = Field(default="adb", validation_alias="ADB_BINARY")
    adb_server_host: str | None = Field(default=None, validation_alias="ADB_SERVER_HOST")
    adb_server_port: int = Field(default=5037, ge=1, le=65535, validation_alias="ADB_SERVER_PORT")
    poll_interval_seconds: float = Field(
        default=30.0, ge=1.0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_POLL_INTERVAL"
    )

    @field_validator("adb_server_host", mode="before")
    @classmethod
    def normalize_server_host(cls, value: object) -> object:
        return None if value == "" else value

    registry_path: str | Path = Field(
        default="data/devices.sqlite3", validation_alias="ANDROID_FLEET_REGISTRY_PATH"
    )
    seed_fake_devices: bool = Field(
        default=True, validation_alias="ANDROID_FLEET_SEED_FAKE_DEVICES"
    )
    enable_mdns: bool = Field(default=False, validation_alias="ANDROID_FLEET_MDNS")
    connect_timeout: float = Field(
        default=10, gt=0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_CONNECT_TIMEOUT"
    )
    backoff_initial: float = Field(
        default=2, gt=0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_BACKOFF_INITIAL"
    )
    backoff_max: float = Field(
        default=60, gt=0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_BACKOFF_MAX"
    )
    control_token: SecretStr | None = Field(
        default=None, validation_alias="ANDROID_FLEET_CONTROL_TOKEN"
    )

    @field_validator("control_token", mode="before")
    @classmethod
    def normalize_control_token(cls, value: object) -> object:
        return None if value == "" else value

    metrics_interval_seconds: float = Field(
        default=30, ge=1, allow_inf_nan=False, validation_alias="ANDROID_FLEET_METRICS_INTERVAL"
    )
    metrics_command_timeout: float = Field(
        default=5,
        gt=0,
        le=30,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_METRICS_COMMAND_TIMEOUT",
    )
    metrics_cycle_timeout: float = Field(
        default=20,
        gt=0,
        le=120,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_METRICS_CYCLE_TIMEOUT",
    )
    metrics_parallel_devices: int = Field(
        default=4, ge=1, le=32, validation_alias="ANDROID_FLEET_METRICS_PARALLEL_DEVICES"
    )
    metrics_max_age_seconds: float = Field(
        default=90, gt=0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_METRICS_MAX_AGE"
    )
    capability_refresh_seconds: float = Field(
        default=300,
        ge=1,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_CAPABILITY_REFRESH_INTERVAL",
    )
    history_path: str | Path = Field(
        default="data/metrics.sqlite3", validation_alias="ANDROID_FLEET_HISTORY_PATH"
    )
    history_retention_seconds: int = Field(
        default=604800,
        ge=60,
        le=31536000,
        validation_alias="ANDROID_FLEET_HISTORY_RETENTION_SECONDS",
    )
    history_max_points: int = Field(
        default=1_000_000, ge=1, le=10_000_000, validation_alias="ANDROID_FLEET_HISTORY_MAX_POINTS"
    )

    alerts_path: str | Path | None = Field(
        default=None, validation_alias="ANDROID_FLEET_ALERTS_PATH"
    )
    alerts_interval_seconds: float = Field(
        default=5,
        ge=1,
        le=300,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_ALERTS_INTERVAL",
    )

    rbac_credentials: SecretStr | None = Field(
        default=None, validation_alias="ANDROID_FLEET_RBAC_CREDENTIALS"
    )
    anonymous_viewer: bool = Field(default=False, validation_alias="ANDROID_FLEET_ANONYMOUS_VIEWER")
    audit_retention_seconds: int = Field(
        default=7776000, ge=3600, validation_alias="ANDROID_FLEET_AUDIT_RETENTION_SECONDS"
    )
    operations_path: str | Path | None = Field(
        default=None, validation_alias="ANDROID_FLEET_OPERATIONS_PATH"
    )
    operations_concurrency: int = Field(
        default=4, ge=1, le=32, validation_alias="ANDROID_FLEET_OPERATIONS_CONCURRENCY"
    )
    operations_max_queued: int = Field(
        default=100, ge=1, le=10000, validation_alias="ANDROID_FLEET_OPERATIONS_MAX_QUEUED"
    )
    operations_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=300,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_OPERATIONS_TIMEOUT_SECONDS",
    )
    apk_max_bytes: int = Field(
        default=67108864, ge=1024, le=536870912, validation_alias="ANDROID_FLEET_APK_MAX_BYTES"
    )
    screenshot_max_bytes: int = Field(
        default=16777216,
        ge=1024,
        le=67108864,
        validation_alias="ANDROID_FLEET_SCREENSHOT_MAX_BYTES",
    )
    screenshot_retention_seconds: int = Field(
        default=3600, ge=60, le=86400, validation_alias="ANDROID_FLEET_SCREENSHOT_RETENTION_SECONDS"
    )
    alerts_retention_seconds: int = Field(
        default=2592000, ge=60, validation_alias="ANDROID_FLEET_ALERTS_RETENTION_SECONDS"
    )

    operations_timeouts: dict[str, float] = Field(
        default_factory=dict, validation_alias="ANDROID_FLEET_OPERATIONS_TIMEOUTS"
    )

    @field_validator("operations_timeouts")
    @classmethod
    def bounded_operation_timeouts(cls, value: dict[str, float]) -> dict[str, float]:
        import math

        if any(not math.isfinite(timeout) or not 0 < timeout <= 300 for timeout in value.values()):
            raise ValueError("Operation timeouts must be finite and between zero and 300 seconds")
        return value
