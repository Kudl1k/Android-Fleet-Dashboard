"""Low-cardinality screen operational metrics; exporter owns metric names."""


def render_screen_metrics(values: dict[str, float]) -> bytes:
    names = {
        "active_sessions": "android_screen_active_sessions",
        "active_viewers": "android_screen_active_viewers",
        "active_controllers": "android_screen_active_controllers",
        "session_failures": "android_screen_session_failures_total",
        "cleanup_failures": "android_screen_cleanup_failures_total",
        "bytes_transferred": "android_screen_bytes_transferred_total",
        "dropped_frames": "android_screen_dropped_frames_total",
        "startup_seconds_total": "android_screen_startup_duration_seconds_sum",
        "sessions_started": "android_screen_startup_duration_seconds_count",
        "resource_limit_rejections": "android_screen_resource_limit_rejections_total",
    }
    return "".join(f"{name} {values[key]}\n" for key, name in names.items()).encode()
