# API conventions

REST uses `/api/v1`, UTC timestamps, stable UUID device IDs and lower_snake_case enums. Registration/configuration remains separate from observations: a registered device can be offline, unavailable or pairing-required. Discovery never silently registers devices. Generated `/docs` and `/openapi.json` describe exact schemas.

## Implemented routes

| Method | Route | Result |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/ready` | 200 ready or 503 unavailable |
| GET | `/metrics` | Prometheus exposition |
| GET | `/api/v1/devices` | Registered fleet with observed runtime information |
| POST | `/api/v1/devices` | Register a device; 201 |
| GET | `/api/v1/devices/{device_id}` | One registered device |
| PATCH | `/api/v1/devices/{device_id}` | Update registration configuration |
| DELETE | `/api/v1/devices/{device_id}` | Remove registration; 204 |
| POST | `/api/v1/devices/{device_id}/connect` | Enable connection/reconnection; 202 |
| POST | `/api/v1/devices/{device_id}/disconnect` | Disconnect and disable automatic reconnection; 200 |
| GET | `/api/v1/devices/{device_id}/metrics` | Current normalized values, observation time and stale flag |
| GET | `/api/v1/devices/{device_id}/metrics/history` | Paginated historical values |
| GET | `/api/v1/devices/{device_id}/capabilities` | Observed capabilities |
| POST | `/api/v1/devices/{device_id}/capabilities/refresh` | Reprobe online device; 200, offline 409 |
| GET | `/api/v1/discovery/devices` | Discovery envelope: `devices`, `mdns_enabled`, `mdns_available` |
| GET | `/api/v1/settings` | Runtime cadences with defaults, limits and per-device overrides (`device.read`) |
| PUT | `/api/v1/settings` | `{"values": {"metrics_interval_seconds": 10}}`; `null` restores the environment default (`device.manage`, audited) |
| PUT | `/api/v1/settings/devices/{device_id}` | Per-device `metrics_interval_seconds` override; `null` removes it (`device.manage`, audited) |

Runtime settings cover only cadences that can change without a restart: `metrics_interval_seconds` (5–3600, per-device capable), `poll_interval_seconds` (5–3600) and `alerts_interval_seconds` (2–600). They persist in `settings.sqlite3` beside the registry and take effect within a second. Secrets, ports, paths and limits remain environment-only and are not exposed through this API.

Readiness reflects storage, metrics-worker, alert-worker and ADB discovery/polling availability, independent of fleet size. An accessible server with zero devices can be ready; offline devices alone do not make the manager unready. HTTP 202 accepts connection intent rather than guaranteeing an online device.

Registration includes `name`, `connection_type`, `host`, `port`, USB-only `serial`, optional `mdns_service`, string `metadata`, and `auto_connect` (default true). Network registrations require host and port as the manual fallback. USB uses serial. A configured mDNS service is the exact connect instance name, for example `adb-example._adb-tls-connect._tcp`; pairing services are not connect targets. No association is inferred merely because advertisements share a host. Real registrations use a generated UUID; fake-only seed IDs preserve M0 demo labels. The registry assigns the UUID; ADB serials and dynamic ports can change independently.

A manual disconnect persists `auto_connect=false`. Explicit connect or PATCH setting `auto_connect=true` resumes reconnect intent. Discovery returns transports and optional service advertisements, including pairing-required records; listing services performs no connect or pairing action.

Application errors use `{"error": {"code": "machine_readable_code", "message": "safe description"}}`. Distinguish missing registration (404), conflicting/unsupported state (409), invalid input (422), and unavailable infrastructure (503). Never expose subprocess diagnostics or secrets through errors.

## Authorization

Protected endpoints enforce permissions on the server. Device mutations require
`device.manage`, alert mutations require `alerts.manage`, and reads require their
respective read permission. No tokenless loopback mutation exception remains.
The existing control bearer token is an administrator credential; named hashed
credentials provide viewer/operator/administrator identities. Optional anonymous
viewer access is an explicit compatibility opt-in; protected reads require
authentication by default in M4.5. Invalid supplied credentials never fall back to anonymous access. See
[authorization and audit](AUTHORIZATION.md) for provisioning and the full matrix.
Health/readiness/Prometheus and generated API schemas remain deployment endpoints.

## M4 device control

| Method | Route | Result / permission |
| --- | --- | --- |
| GET | `/api/v1/auth/me` | Identity, role and permissions |
| POST | `/api/v1/devices/{device_id}/operations` | Queue allowlisted action; 202; action-specific permission |
| POST | `/api/v1/devices/{device_id}/apk` | Validated APK upload queues installation; 202; `apps.install` |
| GET | `/api/v1/operations` | Filtered operation history; `operations.read` |
| GET | `/api/v1/operations/{operation_id}` | Persistent operation status; `operations.read` |
| POST | `/api/v1/operations/{operation_id}/cancel` | Safe cancellation; `operations.cancel` plus ownership |
| GET | `/api/v1/operations/{operation_id}/screenshot` | Protected PNG download; `control.screen` |
| GET | `/api/v1/audit` | Paginated filtered audit; `audit.read` |

Operation request: `{ "action": "apps.inspect", "package": "com.example.app" }`.
Optional `property` selects an approved property. Destructive requests require
literal JSON `confirmed:true`; strings/numbers cannot substitute confirmation.
Unknown fields are rejected. Accepted requests return a queued record, never a
promise of device success. Poll status until a terminal state.

Operation fields: `id`, `device_id`, `action`, `actor`, `role`, `state`,
`created_at`, `started_at`, `finished_at`, `duration`, `result`, `error`,
`cancellable`. Operation/audit timestamps are Unix seconds; existing monitoring
and alert timestamps retain ISO UTC formats. States are `queued`, `running`,
`succeeded`, `failed`, `cancelled`, `timed_out`. Duration measures execution,
excluding queue wait. Cancellation/timeout can stop local execution but cannot
undo device effects. Operators can cancel their own cancellable operations;
administrators can cancel any cancellable operation.

History filters: `device_id`, `action`, `state`, `limit` (1–200, default 50),
`offset`. Response: `{items,total}`. Audit filters: `actor`, `device_id`,
`action`, `authorization`, `outcome`, `limit`, `offset`; response includes
`items,total,limit,offset`. Audit has no public update/delete API.

APK upload uses a raw body with `Content-Type: application/vnd.android.package-archive`,
not multipart or a server path. Default limit is 64 MiB; oversized uploads return
413, malformed archives 400, saturated upload capacity 429, upload deadline 408.
Screenshot downloads have `Cache-Control:no-store`, PNG content type and download
filename; images never have public static URLs and expire after an hour by default.

See [device control](DEVICE_CONTROL.md) for action permissions, result shapes,
unsupported capabilities and execution bounds. Arbitrary shell/terminal, logcat,
and file transfer remain deferred. M5 adds the scoped screen transport described below.

## Metric queries

Current responses contain `device_id`, `state`, `observed_at`, `stale`, and `values` with `name`, `value`, `unit`, `kind`, and dimension `labels`. Offline, expired or unsupported observations have no current values. Reads never initiate ADB commands.

History requires timezone-aware `start` and `end` (start inclusive, end exclusive), optional domain `metric` name, `limit` (1–10000, default 1000), and opaque `cursor`. Response includes `points` and nullable `next_cursor`. Reuse the same range/filter for subsequent pages. Range must fit configured retention; malformed queries/cursors return structured 422. Unknown devices return 404; unavailable history storage returns 503. See [metrics](METRICS.md) for names, units, retention and pagination limits.

## M3 alerts

| Method | Route | Result |
| --- | --- | --- |
| GET | `/api/v1/alerts/rules` | Global and per-device rules |
| POST | `/api/v1/alerts/rules` | Create rule; authenticated, 201 |
| PATCH | `/api/v1/alerts/rules/{rule_id}` | Update rule; authenticated |
| DELETE | `/api/v1/alerts/rules/{rule_id}` | Delete rule; authenticated, 204 |
| GET | `/api/v1/alerts` | Filtered active alerts and history |
| POST | `/api/v1/alerts/{event_id}/acknowledge` | Acknowledge firing event; authenticated |

Rule fields: `id`, `name`, `condition`, nullable `device_id` (null means global),
`severity`, `threshold`, `duration_seconds`, `hysteresis`, `enabled`. One rule per
condition and scope is allowed. PATCH merges supplied fields with the stored rule;
`device_id:null` selects global scope. Per-device rules override globals for the
same condition, including when disabled. See [alert configuration](ALERTING.md)
for conditions, units, defaults and lifecycle semantics.

Event fields: `id`, `rule_id`, `device_id`, `device_name`, `condition`, `severity`,
`threshold`, nullable `value`, `state`, `started_at`, nullable `fired_at`,
`acknowledged_at`, `resolved_at`, and `updated_at` (UTC timestamps). Rules/events
contain no privileged credentials. Event identity deduplicates continued violations.

List queries accept `state=pending|firing|acknowledged|resolved`,
`severity=info|warning|critical`, `device_id`, `limit` (1–500, default 100), and
`offset` (default 0). Omit state for history across all states. Responses contain
`items`, `total`, `limit`, `offset`; histories are paginated rather than returned
unbounded. Mutation guards match device controls. Read routes enforce `alerts.read`; optional anonymous viewer access retains
the loopback deployment compatibility mode.

## M5 live screen

| Method | Route | Result |
| --- | --- | --- |
| POST | `/api/v1/devices/{device_id}/screen/sessions` | Create view-only session; 201; `screen:view` |
| GET | `/api/v1/screen/sessions` | Current actor's scoped sessions |
| GET | `/api/v1/screen/sessions/{sid}` | Owner's session details |
| GET | `/api/v1/screen/sessions/{sid}/statistics` | Bytes, drops and startup seconds |
| DELETE | `/api/v1/screen/sessions/{sid}` | Owner stops session |
| POST | `/api/v1/screen/sessions/{sid}/terminate` | Explicit termination; `screen:session:terminate` (administrator for other owners) |
| POST / DELETE | `/api/v1/screen/sessions/{sid}/control` | Acquire exclusive control / release it |
| POST | `/api/v1/screen/sessions/{sid}/ticket` | Single-use stream ticket, expires in 30 seconds |
| WebSocket | `/api/v1/screen/sessions/{sid}/stream` | Authenticated session-bound video and input |

Creation accepts strict JSON `{"max_size":1280,"max_fps":30,"bitrate":4000000,"codec":"h264"}`. Bounds are 320–2560 pixels, 1–60 FPS and 100000–12000000 bit/s. Unknown fields and codecs are rejected. Creation is asynchronous: 201 does not prove the device encoder started. Offline devices return 409 and resource saturation 429. Details contain ID, device ID, owner, creation/activity Unix timestamps, state, requested capabilities, configuration, control ownership, dimensions, statistics and termination reason. States are `starting`, `streaming`, `reconnecting`, `stopping`, `stopped`, `failed`, `timed_out`. Terminal records expire from memory after five minutes; this is not durable history.

Use a bearer-authenticated ticket request, then an allowed-origin WebSocket and first text message `{"ticket":"VALUE"}` within five seconds. Never put a bearer or ticket in the URL. One socket attaches to one session. Server text messages include metadata, status and errors; binary messages contain framed H.264 access units as documented in [architecture](M5_ARCHITECTURE.md). Send `{"type":"ping"}` every ten seconds to keep the session active. Disconnect terminates the session and releases control.

Control acquisition requires an attached streaming session, owner identity, device scope and `screen:control`; competing controllers return 409. Input remains rejected until acquisition. Text JSON is limited to 4096 characters, with 120 control events per second per session. Strict event variants are `pointer` (action, x/y, width/height, pressure/buttons), `key` (allowlisted Android keycode, down/up, repeat/meta), `text` (1–300 characters), and `nav` (back/home/recent/wake/volume_up/volume_down). Pointer dimensions must match the current display. No arbitrary Android keycodes or shell commands are accepted. See generated OpenAPI for exact schema bounds; WebSocket event schemas follow `screen/models.py`.

## M7 terminal, SSH and pairing API

`POST /api/v1/terminal/sessions` accepts connection_type (adb/ssh), registered device_id
or saved profile_id and cols/rows. GET list/detail returns owner metadata/history; DELETE
closes an owned session; POST /{id}/terminate requires terminal:session:terminate.
POST /{id}/ticket issues a single-use ticket; `/api/v1/terminal/sessions/{id}/stream`
authenticates via fleet-terminal.v1 and ticket.<token> WebSocket subprotocols before accept.
Messages are version:1 JSON with input/output/resize/status/error/close/heartbeat types.
See [architecture](M7_ARCHITECTURE.md) for exact schemas and bounds.

`/api/v1/ssh/profiles`: GET list, POST create, PUT /{id} replace, DELETE /{id};
GET /{id}/host-key candidate fingerprint, POST same path {fingerprint} approval,
POST /{id}/test short connection. Manage routes require terminal:profile:manage.
Secrets are accepted only on writes and never returned.

Administrator pairing routes: POST /api/v1/pairing/pair {host,port,code};
POST /api/v1/pairing/connect {host,port}; POST /api/v1/pairing/register {host,port,name};
POST /api/v1/devices/{id}/wireless-port {host,port}. Pairing and connection ports are
separate; verification is actor-bound and expires. GET /api/v1/pairing/allowed-networks lists
approved private IP/CIDR entries; POST with {network} approves one and DELETE with {network}
revokes one. These settings routes require security.manage and changes are audited. See
[configuration](M7_SSH_CONFIGURATION.md).
