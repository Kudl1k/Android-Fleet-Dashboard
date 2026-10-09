# Metrics

Collectors emit normalized `MetricValue(name, value, unit, labels)` inside UTC `MetricSnapshot` objects. They depend on ADB and domain models, never FastAPI or Prometheus. A bounded metric catalog validates names, units, ranges and dimensions. The collector pipeline replaces current snapshots and records local history; HTTP and Prometheus reads consume stored observations without issuing ADB commands.

Use explicit `android_` Prometheus names, base units, ratios from 0–1, and bounded `device_id` labels. Celsius is named explicitly. Network byte counters end in `_total`; capacities such as `android_storage_total_bytes` are gauges. A missing, denied, malformed or unavailable observation is absent. Never fabricate zero telemetry or substitute `MemFree` for `MemAvailable`.

## Exported families

All families use `device_id`; additional dimensions are shown below.

| Family | Type | Meaning / extra labels |
| --- | --- | --- |
| `android_device_up` | Gauge | Online ADB transport, 1 or 0 |
| `android_device_rooted` | Gauge | Observed root availability; unknown/offline omitted |
| `android_device_last_seen_timestamp_seconds` | Gauge | Last successful device observation, Unix seconds |
| `android_metrics_last_collection_timestamp_seconds` | Gauge | Fresh snapshot observation, Unix seconds |
| `android_cpu_usage_ratio` | Gauge | Aggregate CPU usage |
| `android_cpu_core_usage_ratio` | Gauge | Per-core CPU usage; `core` |
| `android_cpu_frequency_hz` | Gauge | Observed frequency; `core` |
| `android_memory_total_bytes` | Gauge | Physical RAM |
| `android_memory_available_bytes` | Gauge | RAM available without swapping |
| `android_memory_used_bytes` | Gauge | Total minus available RAM |
| `android_swap_used_bytes` | Gauge | Swap total minus free |
| `android_battery_level_ratio` | Gauge | Battery level divided by scale |
| `android_battery_temperature_celsius` | Gauge | Battery temperature |
| `android_battery_voltage_volts` | Gauge | Battery voltage |
| `android_battery_charging` | Gauge | Observed charging status, 0 or 1; unknown omitted |
| `android_battery_status` | Gauge | Android battery status code, integer 1–5 |
| `android_battery_health` | Gauge | Android battery health code, integer 1–7 |
| `android_battery_current_amperes` | Gauge | Current where a supported source exposes it; sign follows source |
| `android_storage_total_bytes` | Gauge | Filesystem capacity; `mount=/data` |
| `android_storage_used_bytes` | Gauge | Filesystem allocation; `mount=/data` |
| `android_storage_free_bytes` | Gauge | Filesystem availability; `mount=/data` |
| `android_network_receive_bytes_total` | Counter | Raw interface received bytes; `interface` |
| `android_network_transmit_bytes_total` | Counter | Raw interface transmitted bytes; `interface` |
| `android_uptime_seconds` | Gauge | Device uptime |
| `android_temperature_celsius` | Gauge | Live thermal temperature; `sensor`, `type` |
| `android_thermal_status` | Gauge | Android thermal severity, integer 0–6 |

CPU dimensions allow cores 0–255. Network interface values are bounded names, with at most 32 distinct interfaces per snapshot. Thermal types use a fixed vocabulary; at most 32 distinct sensor names are exported per snapshot. Only `/data` is a storage dimension. No process IDs, arbitrary paths or raw command output become labels. Duplicate metric identities are emitted once.

## Collection semantics and limitations

CPU prefers `/proc/stat`. The first sample establishes a baseline and does not invent usage; subsequent polls calculate counter deltas. Idle and iowait are treated as idle. Guest counters are already included in user/nice and are not counted twice. Missing cores, nonadvancing counters and backwards/reset counters omit that interval. Baselines must reset after reconnect. If `/proc/stat` is unavailable, supported aggregate `dumpsys cpuinfo` output can provide a fallback; its reporting interval differs from the polling interval. Readable CPU frequency sysfs values are converted from kHz to Hz.

Memory comes from `/proc/meminfo`: Android's `kB` labels denote KiB and are multiplied by 1024. Older kernels can lack `MemAvailable`; dependent used-memory values are then omitted. Battery `dumpsys` units are normalized from tenths Celsius and millivolts. Optional current comes from readable battery sysfs microamp values converted to signed amperes and must not be assumed for every device.

Storage queries `/data` filesystem output, accepting its bounded Android bind-mount descendants while retaining the logical `/data` label; network reads cumulative per-interface counters from `/proc/net/dev` with a supported `ip -s link` fallback, excluding loopback and prioritizing physical/active interfaces within the 32-interface limit; uptime uses `/proc/uptime`. Counters are exported exactly as observed. Reboot or interface resets lower the counter: Prometheus `rate()` handles resets, so the backend does not accumulate an invented offset. Permission and vendor differences can remove individual observations without failing another collector or device.

Thermal collection prefers live temperatures from `dumpsys thermalservice`, excluding cached thresholds and cooling-device state. A readable sysfs fallback converts thermal-zone millidegrees to Celsius. Battery Current Limiter zones are excluded because they may expose electrical values rather than temperature. Sensor names are bounded and sanitized. Thermal status is severity, not a temperature or a direct proof of throttling. Unknown vendor formats remain unsupported.

The manually checked registration named Pixel (probed model SM-A356B, Android 16) exposed the core read-only sources, but this does not establish support across Android versions, OEMs or non-rooted fleets. No metric assumes root. Hardware-specific GPU/NPU/DSP implementations remain deferred and must implement explicit applicability and capability contracts; chipset strings alone do not establish support.

## Freshness, API and local history

Only online devices with a fresh snapshot contribute telemetry. Expired, future-dated or mismatched snapshots are omitted; historical last-seen timestamps remain useful while a device is offline. Set `ANDROID_FLEET_METRICS_INTERVAL` for collection cadence (default 30 seconds) and `ANDROID_FLEET_METRICS_MAX_AGE` for snapshot freshness (default 90 seconds). Bounded command/cycle timeouts and per-device parallelism are configured separately; a metrics worker runs independently of connectivity polling. Prometheus marks disappearing series stale rather than retaining fabricated values.

`GET /api/v1/devices/{device_id}/metrics` returns normalized current observations and freshness metadata. An offline or unsupported device returns no values rather than zero-filled observations. Expired snapshots likewise expose no current values. `GET /api/v1/devices/{device_id}/metrics/history` provides bounded local history with timezone-aware `start`, exclusive `end`, optional domain metric name, `limit`, and opaque `cursor` pagination. Local history is a convenience for the control API; Prometheus remains the long-term monitoring backend.

History uses separate SQLite storage with time retention and a maximum point count. Configure `ANDROID_FLEET_HISTORY_PATH`, `ANDROID_FLEET_HISTORY_RETENTION_SECONDS` and `ANDROID_FLEET_HISTORY_MAX_POINTS`; defaults are `data/metrics.sqlite3`, seven days and one million points. Invalid/nonfinite values are not stored. Retention/capacity eviction can remove old points; the database file can retain previously allocated pages up to its capacity high-water mark. Pagination is ordered by observation time, metric name and labels; cursors apply only to their original device/range/filter. It is not a transactional snapshot of a continuously changing database.

## Grafana

Versioned editable dashboards are provisioned for fleet overview and device detail using datasource UID `prometheus`. Device selection queries `android_device_up` so offline devices remain selectable. Ratios use Grafana's 0–1 percent unit; network graphs use `rate(...[$__rate_interval])`. Missing observations display as missing. Availability, collection age, CPU, RAM, battery, storage, network, thermal and uptime panels do not imply that every device supports every metric. M3 adds backend-managed alerts and a React dashboard; production hardening remains later work.

Battery status maps 1 unknown, 2 charging, 3 discharging, 4 not charging, 5 full.
Health maps 1 unknown, 2 good, 3 overheat, 4 dead, 5 over-voltage, 6 unspecified
failure, 7 cold. Unknown status never fabricates a charging observation.
