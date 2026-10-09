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
file transfer and screen input streams remain deferred to scoped M5 work.

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
