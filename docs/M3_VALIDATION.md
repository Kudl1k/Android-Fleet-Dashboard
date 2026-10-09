# M3 implementation and validation — 2026-10-09

M3 is implemented and deployed at **http://127.0.0.1:8088**. Three specialized
agents audited and completed fleet/detail UI, alert backend, and alerts/management
UI in parallel with bounded file ownership and existing API contracts. The lead
integrated changes, fixed the missing test peer dependency, documented the milestone,
and performed complete validation and deployment. No commits or pushes were made.

## Implemented features

React 19/TypeScript/Vite, TanStack Query, React Router, Recharts and Lucide provide
fleet summaries/search/filter/sort, current device telemetry, identity/capabilities,
freshness, thermal/network/storage information and historical charts with 15m, 1h,
6h, 24h and 7d ranges. Independent queries prevent full-page replacement on polling.
Lazy routes reduce initial JavaScript from about 698KB to 307KB. Existing shared CSS
and native accessible form/dialog controls avoid unnecessary framework dependencies.

Dark/light themes, desktop sidebar/mobile navigation, keyboard skip link, skeletons,
empty/error/offline states, accessible observation tables, confirmations and toast
feedback are included. Cached observations are withheld after device disconnect or
metric fetch failure; unavailable observations are never replaced by zero. Historical
charts break lines across gaps exceeding two minutes.

Management supports authenticated network registration, name/connection edits,
automatic reconnect, reconnect requests, troubleshooting and confirmed removal.
Control tokens remain only in memory; pairing codes and private keys are never entered
or exposed. Only theme preference is stored in browser storage.

Backend-owned alert evaluation runs independently of browser sessions. Eight conditions
cover low battery/storage, high battery/device temperature, CPU/RAM usage, offline and
stale telemetry. Global defaults/per-device overrides, severity, sustained duration,
hysteresis, pending/firing/acknowledged/resolved lifecycle, deduplication and recovery
persist in separate SQLite rules/events. Versioned authenticated mutations and filtered,
paginated history support the alerts UI and in-app new-incident notifications.
Malformed/unsupported metrics cannot trigger metric alerts. See [configuration](ALERTING.md)
and [API](API.md) for exact lifecycle and contract semantics.

## Automated validation

Executed from the repository with the Python 3.13 virtual environment:

```bash
.venv/bin/pytest backend/tests -q
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/mypy backend/src
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

**293 backend tests passed** (including all M0–M2 tests). Ruff lint and formatting
passed for 63 files; mypy passed for 46 source files. **27 frontend tests passed in
7 files**, ESLint/typecheck and production build passed. Coverage includes API hooks,
loading/empty/error/offline fleet states, filtering/sorting, historical gaps/real zero
values, management mutations and draft preservation, alert configuration/acknowledgement,
notification paging/deduplication, threshold/hysteresis/lifecycle, unsupported/missing
metrics, authorization, SQLite schema/persistence, and disconnect/reconnect behavior.
One existing Starlette TestClient/httpx deprecation warning remains; no test failed.

## Docker deployment and persistence

`docker-compose config --quiet` and both `android-manager`/`frontend` production image
builds passed. Compose used its working legacy builder because buildx is unavailable.
Only this project's backend and new frontend were recreated; only its backend was
subsequently restarted for persistence acceptance. Prometheus/Grafana and unrelated
stacks were left running; Colima networking, keys and volumes were retained. Consistent
SQLite registry/history backups were written inside the private volume before deployment.

8088 was free in Docker bindings and host listeners; unrelated port 8080 was preserved.
Published loopback ports remain backend 9000, Prometheus 9090 and Grafana 1900. Frontend
and backend Docker health checks passed; `/ready` returned 200, frontend health returned
200, Grafana database health was OK and Prometheus returned Samsung `android_device_up=1`.
Nginx same-origin API proxying, authorization forwarding and direct detail-route fallback
worked. Unauthorized proxied mutations returned structured 403. No broad CORS was added.

An authenticated temporary disabled per-device rule was created, survived backend restart,
and was removed successfully (204). Alert events remained queryable and default offline
incidents advanced to firing without a browser. All five original registry UUIDs persisted;
518 previous aggregate CPU history points over a six-hour query remained queryable. Restart
retained credentials and the Samsung automatically reconnected. Temporary acceptance
registrations and rules were removed. No existing records were deleted.

## Real-device acceptance

The existing registration named **Pixel**, UUID `2f56dd7a-4fc9-4dd0-b2fb-4825cf078278`,
is **Samsung SM-A356B**, Android **16**, non-rooted. It was online before deployment and
after deployment/restart, using the existing container-local paired ADB server. Current
API returned fresh snapshots containing 94–103 normalized observations during acceptance;
CPU interval warmup can temporarily leave CPU unavailable after restart. Battery, RAM,
storage, network, uptime and thermal telemetry and prior historical charts were available.
This verifies Samsung monitoring/reconnection, not actual Google Pixel or rooted hardware.
The four earlier demo USB registrations remain real persisted registry records but offline;
no fake telemetry is presented for them.

## Browser/UI acceptance

Headless Chromium through temporary Playwright tooling loaded the deployed fleet with
actual Samsung identity, device detail with live/history queries and rendered charts,
alerts, management and native control dialog. Dark desktop and light 390px mobile screenshots
were inspected; mobile fleet had no horizontal overflow and no JavaScript page errors were
reported. Theme switching and direct URL navigation passed.

A browser held the existing token in memory and registered a temporary nonconnecting
network device, edited its name, and removed it through confirmation. All operations
succeeded against the authenticated deployed APIs. Browser local/session storage did
not contain the token. The Samsung configuration was unchanged. Alert acknowledgement
and lifecycle have automated API/component coverage; a production incident was not
acknowledged merely for acceptance. Safari WebDriver required disabled remote automation,
so Chromium was used without changing Safari settings.

## Limits and deferred work

This is a loopback homelab deployment with one shared control token, not users/roles,
per-device authorization, audit identity or TLS hardening. Read APIs remain unauthenticated.
Automated browser checks and inspected screenshots do not replace a full accessibility
or cross-browser/device audit. Actual rooted hardware, Google Pixel, other OEMs, multicast,
USB passthrough and changed Wireless Debugging ports without manual input remain unverified.
External notifications are outside M3. Alert event history has pagination but no retention
policy; large fleets/history warrant load testing and retention/aggregation policies.
Metric history retains its existing seven-day/global-point limits. Dependency/image
locking and long-duration hardware soak remain hardening work; hosted CI was not run.

Recommended M4: introduce actor authorization and audit logging before bounded control
jobs, then scoped reboot/process/package/file actions with cancellation and explicit
permissions. Add alert retention and longer restart/disconnect soak validation. Terminal,
logcat and arbitrary command UI remain deferred until those controls are safe.
