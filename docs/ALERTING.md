# Alert configuration

The backend evaluates normalized observations every five seconds, independently
of browser sessions. Set `ANDROID_FLEET_ALERTS_INTERVAL` to change the cadence.
Rules and events persist in a separate SQLite database beside the device registry;
Compose stores `/var/lib/android-fleet/alerts.sqlite3` in the existing private volume.
Schema version 1 initializes additively and rejects newer unsupported schemas.

Default rules are seeded once, so deleting a default survives restart. All defaults
have warning severity, a 60-second sustained duration, and are enabled:

| Condition | Threshold | Recovery hysteresis | Units |
| --- | --- | --- | --- |
| battery_low | 0.15 | 0.03 | remaining ratio |
| battery_temperature | 45 | 3 | Celsius |
| device_temperature | 70 | 5 | maximum observed Celsius |
| cpu_high | 0.90 | 0.05 | utilization ratio |
| memory_high | 0.90 | 0.05 | used / total RAM |
| storage_low | 0.10 | 0.03 | free / total `/data` |
| offline | 120 | 0 | seconds since last seen |
| telemetry_stale | 120 | 0 | seconds since valid online telemetry |

Low conditions trigger strictly below threshold; high conditions trigger strictly
above it. Offline/stale thresholds plus sustained duration determine firing time.
For example, offline defaults fire after approximately 180 seconds plus scheduling
latency. Devices never seen use this process startup as their offline baseline.

Use the Alerts rule editor or authenticated [REST routes](API.md). Ratios use 0..1,
not percentages. `device_id:null` selects a global rule. One rule per condition and
scope is allowed. A per-device override takes precedence even when disabled. Levels
are info, warning and critical. Changing a rule resolves its old active incidents
and starts a new evaluation window under the new configuration.

A violation creates a pending event. Sustained violations become firing; acknowledgement
records operator attention and keeps evaluation running. Recovery resolves both firing
and acknowledged events. Hysteresis requires recovery beyond the threshold: a 15%
low-battery rule with 3% hysteresis resolves at 18%. A unique active rule/device index
and serialized evaluation deduplicate incidents. Resolved events remain in history.
Deleting rules or registrations, or disabling effective rules, resolves their incidents.

Unsupported metrics never trigger metric alerts. Missing, invalid, disconnected or
expired observations break pending metric windows; they do not claim a firing metric
condition recovered. Offline and stale telemetry have their own rules. Stale telemetry
is evaluated for online devices only. Reconnect invalidates pending metric evidence.
Restart preserves firing/acknowledged events and rules, while restarting pending metric
windows where downtime provides no continuous evidence.

The dashboard polls alerts, displays active severity counts, provides paginated
history, and shows toasts for newly firing incidents after the initial load. There
is no email, webhook or external notification delivery in M3. Event history currently
has no retention policy; M4/hardening should define archival and capacity limits.

## M4 reliability and retention

`ANDROID_FLEET_ALERTS_RETENTION_SECONDS` defaults to 30 days. Cleanup expires only
resolved incidents according to resolution/update time and preserves active pending,
firing and acknowledged incidents. Background evaluation owns minute maintenance independently
of browsers. Prolonged offline deduplication and repeated reconnect lifecycle have
regression coverage; generation changes continue to invalidate stale pending telemetry.

Prometheus now exposes `android_alert_evaluation_healthy`,
`android_alert_evaluations_total`, `android_alert_evaluation_errors_total`,
`android_alert_evaluation_duration_seconds` and
`android_alert_last_evaluation_timestamp_seconds`. Evaluation failures mark health
unavailable and successful subsequent evaluation recovers it. Retention removes
rows, not SQLite allocated pages or copies in backups. Notification delivery remains
outside M4.
