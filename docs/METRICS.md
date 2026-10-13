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
| `android_battery_charge_ampere_hours` | Gauge | Remaining charge from `dumpsys battery` "Charge counter" (µAh); 0 is treated as unsupported |
| `android_battery_charge_full_ampere_hours` | Gauge | Current full capacity (`charge_full`, read through `su` when rooted) |
| `android_battery_charge_full_design_ampere_hours` | Gauge | Design capacity (`charge_full_design`); full/design is the wear ratio |
| `android_battery_cycle_count` | Gauge | Fuel-gauge charge cycle counter |
| `android_device_info` | Gauge | Always 1; `manufacturer`, `model`, `android_version`, `soc`, `kernel` from the last probe |
| `android_cpu_max_frequency_hz` | Gauge | Hardware maximum (`cpuinfo_max_freq`); `core` |
| `android_cpu_frequency_limit_hz` | Gauge | Current policy ceiling (`scaling_max_freq`); `core` |
| `android_cpu_frequency_capped` | Gauge | 1 when any core's ceiling is below its hardware maximum |
| `android_zram_disk_size_bytes` | Gauge | Configured ZRAM swap size, summed over zram devices |
| `android_zram_original_data_bytes` | Gauge | Uncompressed data stored in ZRAM |
| `android_zram_compressed_data_bytes` | Gauge | Compressed size of that data |
| `android_zram_memory_used_bytes` | Gauge | RAM consumed by ZRAM including allocator overhead |
| `android_gpu_usage_ratio` | Gauge | GPU busy ratio (Adreno kgsl or Mali `utilization`) |
| `android_gpu_frequency_hz` | Gauge | Current GPU clock |
| `android_gpu_max_frequency_hz` | Gauge | Maximum GPU clock |
| `android_process_count` | Gauge | Number of processes visible in `/proc` |
| `android_process_cpu_ratio` | Gauge | Top 5 processes by CPU, in cores (1 = one busy core); `process` |
| `android_process_memory_bytes` | Gauge | Top 5 processes by resident memory; `process` |

CPU dimensions allow cores 0–255. Network interface values are bounded names, with at most 32 distinct interfaces per snapshot. Thermal types use a fixed vocabulary; at most 32 distinct sensor names are exported per snapshot. Only `/data` is a storage dimension. No process IDs, arbitrary paths or raw command output become labels. Duplicate metric identities are emitted once.

## Collection semantics and limitations

CPU prefers `/proc/stat`. The first sample establishes a baseline and does not invent usage; subsequent polls calculate counter deltas. Idle and iowait are treated as idle. Guest counters are already included in user/nice and are not counted twice. Missing cores, nonadvancing counters and backwards/reset counters omit that interval. Baselines must reset after reconnect. If `/proc/stat` is unavailable, supported aggregate `dumpsys cpuinfo` output can provide a fallback; its reporting interval differs from the polling interval. Readable CPU frequency sysfs values are converted from kHz to Hz.

Memory comes from `/proc/meminfo`: Android's `kB` labels denote KiB and are multiplied by 1024. Older kernels can lack `MemAvailable`; dependent used-memory values are then omitted. Battery `dumpsys` units are normalized from tenths Celsius and millivolts. Optional current comes from readable battery sysfs microamp values converted to signed amperes and must not be assumed for every device.

Storage queries `/data` filesystem output, accepting its bounded Android bind-mount descendants while retaining the logical `/data` label; network reads cumulative per-interface counters from `/proc/net/dev` with a supported `ip -s link` fallback, excluding loopback and prioritizing physical/active interfaces within the 32-interface limit; uptime uses `/proc/uptime`. Counters are exported exactly as observed. Reboot or interface resets lower the counter: Prometheus `rate()` handles resets, so the backend does not accumulate an invented offset. Permission and vendor differences can remove individual observations without failing another collector or device.

Thermal collection prefers live temperatures from `dumpsys thermalservice`, excluding cached thresholds and cooling-device state. A readable sysfs fallback converts thermal-zone millidegrees to Celsius. Battery Current Limiter zones are excluded because they may expose electrical values rather than temperature. Sensor names are bounded and sanitized. Thermal status is severity, not a temperature or a direct proof of throttling. Unknown vendor formats remain unsupported.

The manually checked registration named Pixel (probed model SM-A356B, Android 16) exposed the core read-only sources, but this does not establish support across Android versions, OEMs or non-rooted fleets. No metric assumes root; root only widens what the same collectors can read. Adreno and Mali GPU backends exist (see below); NPU/DSP sources remain future backends under the same evidence rule: chipset strings alone do not establish support.

## Root-aware and vendor collectors

ZRAM, GPU, process and CPU-ceiling collectors each run one bounded read-only shell script per poll. When the probe observed root (`ROOT_SHELL`), the script runs through `su -c`, because SELinux commonly hides `/proc/<pid>`, thermal zones and vendor sysfs from the shell user; a denied or failing `su` falls back to the unprivileged shell. Thermal sysfs and `/proc/stat` use the same elevation only as a fallback. Magisk should allow uid 2000 without notifications (see `device-setup/`), otherwise every poll raises a toast.

GPU backends are selected by sysfs evidence, not chipset names: Qualcomm Adreno via `/sys/class/kgsl/kgsl-3d0` (`gpu_busy_percentage`, else the `gpubusy` busy/total window; clocks in Hz) and Arm Mali (Google Tensor, Exynos, MediaTek) via `/sys/devices/platform/*.mali` or `/sys/class/misc/mali0/device` (`utilization` percent, clocks in kHz). Unknown GPUs produce no observations. New platforms, including NPU/DSP sources, are added as further backends in `collectors/gpu.py` or a sibling collector with the same evidence rule. The Mali paths are unverified on the lab's Pixel 9 Pro until hardware acceptance.

On 2026-10-13 the exact collector commands were run read-only through the root shell of the lab Pixel 3a XL (SDM670, Android 12, kernel 4.9) and replayed through the probe, pipeline and exporter: all families above were produced, including Adreno GPU, ZRAM, CPU ceilings, 13 thermal sensors and processes. Two defects found there are fixed: Android 11+ toybox `df -k /data` names the `/data_mirror/...` bind of the same filesystem (storage was dropped), and zygote-spawned processes keep the generic comm `main`, so their argv[0] is preferred. The battery `Charge counter` format was observed on that phone; the `charge_full`, `charge_full_design` and `cycle_count` sysfs files were added afterwards and are not yet verified on lab hardware. This was not an ADB-transport acceptance; the adb shell user (uid 2000) and the real polling loop remain to be verified.

ZRAM uses `mm_stat`, or the separate `orig_data_size`/`compr_data_size`/`mem_used_total` files on kernels before 4.2; an unconfigured device (disksize 0) is skipped. Process CPU is the utime+stime delta between polls divided by elapsed time in USER_HZ (100) ticks; the first poll after start or reconnect is a baseline only, and PID reuse is detected through the process start time. RSS assumes 4 KiB pages. Names prefer the full `argv[0]` from `cmdline` over the 15-byte kernel `comm`; only the top five per dimension become labels, so cardinality stays bounded while names may change over time.

A frequency ceiling below the hardware maximum is evidence of capping, which thermal mitigation causes through cpufreq cooling devices but power HAL policies can also cause. Dashboards show it next to temperatures and the Android thermal status rather than labelling it throttling on its own.

## Freshness, API and local history

Only online devices with a fresh snapshot contribute telemetry. Expired, future-dated or mismatched snapshots are omitted; historical last-seen timestamps remain useful while a device is offline. Set `ANDROID_FLEET_METRICS_INTERVAL` for collection cadence (default 30 seconds) and `ANDROID_FLEET_METRICS_MAX_AGE` for snapshot freshness (default 90 seconds). Bounded command/cycle timeouts and per-device parallelism are configured separately; a metrics worker runs independently of connectivity polling. Prometheus marks disappearing series stale rather than retaining fabricated values.

`GET /api/v1/devices/{device_id}/metrics` returns normalized current observations and freshness metadata. An offline or unsupported device returns no values rather than zero-filled observations. Expired snapshots likewise expose no current values. `GET /api/v1/devices/{device_id}/metrics/history` provides bounded local history with timezone-aware `start`, exclusive `end`, optional domain metric name, `limit`, and opaque `cursor` pagination. Local history is a convenience for the control API; Prometheus remains the long-term monitoring backend.

History uses separate SQLite storage with time retention and a maximum point count. Configure `ANDROID_FLEET_HISTORY_PATH`, `ANDROID_FLEET_HISTORY_RETENTION_SECONDS` and `ANDROID_FLEET_HISTORY_MAX_POINTS`; defaults are `data/metrics.sqlite3`, seven days and one million points. Invalid/nonfinite values are not stored. Retention/capacity eviction can remove old points; the database file can retain previously allocated pages up to its capacity high-water mark. Pagination is ordered by observation time, metric name and labels; cursors apply only to their original device/range/filter. It is not a transactional snapshot of a continuously changing database.

## Grafana

Versioned editable dashboards are provisioned for fleet overview and device detail using datasource UID `prometheus`. Device selection queries `android_device_up` so offline devices remain selectable. Ratios use Grafana's 0–1 percent unit; network graphs use `rate(...[$__rate_interval])`. Missing observations display as missing. Availability, collection age, CPU, RAM, battery, storage, network, thermal and uptime panels do not imply that every device supports every metric. M3 adds backend-managed alerts and a React dashboard; production hardening remains later work.

Battery status maps 1 unknown, 2 charging, 3 discharging, 4 not charging, 5 full.
Health maps 1 unknown, 2 good, 3 overheat, 4 dead, 5 over-voltage, 6 unspecified
failure, 7 cold. Unknown status never fabricates a charging observation.
