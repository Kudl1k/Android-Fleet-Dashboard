import ipaddress
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_pairing_network(value: str) -> str:
    network = ipaddress.ip_network(value.strip(), strict=False)
    if isinstance(network, ipaddress.IPv4Network):
        valid_range = network.prefixlen >= 16 and any(
            network.subnet_of(ipaddress.IPv4Network(candidate))
            for candidate in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
    else:
        valid_range = network.prefixlen >= 48 and network.subnet_of(
            ipaddress.IPv6Network("fc00::/7")
        )
    if not valid_range:
        raise ValueError(
            "Pairing CIDRs must be private LAN ranges no broader than IPv4 /16 or IPv6 /48"
        )
    return str(network)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", populate_by_name=True)

    fake_adb: bool = Field(default=True, validation_alias="ANDROID_FLEET_FAKE_ADB")
    adb_binary: str = Field(default="adb", validation_alias="ADB_BINARY")
    adb_server_host: str | None = Field(default=None, validation_alias="ADB_SERVER_HOST")
    adb_server_port: int = Field(default=5037, ge=1, le=65535, validation_alias="ADB_SERVER_PORT")
    poll_interval_seconds: float = Field(
        default=15.0, ge=1.0, allow_inf_nan=False, validation_alias="ANDROID_FLEET_POLL_INTERVAL"
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
        default=15, ge=1, allow_inf_nan=False, validation_alias="ANDROID_FLEET_METRICS_INTERVAL"
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
    terminal_adb_enabled: bool = Field(
        default=False, validation_alias="ANDROID_FLEET_TERMINAL_ADB_ENABLED"
    )
    terminal_max_sessions: int = Field(
        default=16, ge=1, le=128, validation_alias="ANDROID_FLEET_TERMINAL_MAX_SESSIONS"
    )
    terminal_max_per_user: int = Field(
        default=4, ge=1, le=32, validation_alias="ANDROID_FLEET_TERMINAL_MAX_PER_USER"
    )
    terminal_max_per_device: int = Field(
        default=2, ge=1, le=8, validation_alias="ANDROID_FLEET_TERMINAL_MAX_PER_DEVICE"
    )
    terminal_idle_seconds: float = Field(
        default=300,
        ge=5,
        le=3600,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_TERMINAL_IDLE_SECONDS",
    )
    terminal_lifetime_seconds: float = Field(
        default=3600,
        ge=10,
        le=86400,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_TERMINAL_LIFETIME_SECONDS",
    )
    terminal_queue_chunks: int = Field(
        default=16, ge=1, le=64, validation_alias="ANDROID_FLEET_TERMINAL_QUEUE_CHUNKS"
    )
    terminal_path: Path | None = Field(default=None, validation_alias="ANDROID_FLEET_TERMINAL_PATH")
    terminal_allowed_origins: tuple[str, ...] = Field(
        default=("http://127.0.0.1:8088", "http://localhost:8088"),
        validation_alias="ANDROID_FLEET_TERMINAL_ALLOWED_ORIGINS",
    )
    ssh_encryption_key: SecretStr | None = Field(
        default=None, validation_alias="ANDROID_FLEET_SSH_ENCRYPTION_KEY"
    )
    ssh_destinations: list[str] = Field(
        default_factory=list, validation_alias="ANDROID_FLEET_SSH_DESTINATIONS"
    )
    pairing_allowed_hosts: tuple[str, ...] = Field(
        default=(), validation_alias="ANDROID_FLEET_PAIRING_ALLOWED_HOSTS"
    )

    @field_validator("pairing_allowed_hosts")
    @classmethod
    def validate_pairing_networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        try:
            return tuple(normalize_pairing_network(value) for value in values)
        except ValueError as exc:
            raise ValueError("Pairing destinations must be private IPs or bounded CIDRs") from exc

    pairing_timeout: float = Field(
        default=15,
        ge=1,
        le=60,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_PAIRING_TIMEOUT",
    )
    pairing_attempts_per_minute: int = Field(
        default=5, ge=1, le=20, validation_alias="ANDROID_FLEET_PAIRING_ATTEMPTS_PER_MINUTE"
    )
    screen_server_path: Path = Field(
        default=Path("/opt/scrcpy/scrcpy-server"),
        validation_alias="ANDROID_FLEET_SCREEN_SERVER_PATH",
    )
    screen_max_sessions: int = Field(
        default=4, ge=1, le=32, validation_alias="ANDROID_FLEET_SCREEN_MAX_SESSIONS"
    )
    screen_max_per_device: int = Field(
        default=2, ge=1, le=8, validation_alias="ANDROID_FLEET_SCREEN_MAX_PER_DEVICE"
    )
    screen_max_per_user: int = Field(
        default=2, ge=1, le=8, validation_alias="ANDROID_FLEET_SCREEN_MAX_PER_USER"
    )
    screen_idle_seconds: float = Field(
        default=30,
        ge=5,
        le=300,
        allow_inf_nan=False,
        validation_alias="ANDROID_FLEET_SCREEN_IDLE_SECONDS",
    )
    screen_queue_frames: int = Field(
        default=8, ge=1, le=32, validation_alias="ANDROID_FLEET_SCREEN_QUEUE_FRAMES"
    )
    screen_allowed_origins: tuple[str, ...] = Field(
        default=("http://127.0.0.1:8088", "http://localhost:8088"),
        validation_alias="ANDROID_FLEET_SCREEN_ALLOWED_ORIGINS",
    )
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
