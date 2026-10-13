# Docker deployment

The existing Colima bridge network and persistent volumes are retained. The backend
owns its ADB server and keeps authenticated pairing keys in `adb-keys`; port 5037 is
never exposed. Registry, metrics history and alerts use separate SQLite files in
`device-registry`. Do not run `down -v` or remove these volumes during upgrades.

Configure `.env` from `.env.example` for a new installation. Preserve an existing
`.env`; set a strong `ANDROID_FLEET_CONTROL_TOKEN` for management and alert mutations.
For hardware, set `ANDROID_FLEET_FAKE_ADB=false` and preserve existing pairing keys.

```bash
docker-compose config --quiet
docker-compose build android-manager frontend
docker-compose up -d --no-deps android-manager
docker-compose up -d --no-deps frontend
docker-compose ps
```

The equivalent `docker compose` commands work where that CLI plugin is installed.
These commands update only this project's backend and frontend. Do not restart
unrelated stacks or change Colima networking.

| Service | Local URL |
| --- | --- |
| Web dashboard | http://127.0.0.1:8088 |
| Backend API / OpenAPI | http://127.0.0.1:9000/docs |
| Prometheus | http://127.0.0.1:9090 |
| Grafana | http://127.0.0.1:1900 |

8088 was checked against current host listeners and Docker bindings for M3; 8080
is occupied by an unrelated service. `ANDROID_FLEET_FRONTEND_PORT` can select another
free port. Existing ports are unchanged and all project ports remain loopback only.

The production frontend is a Vite build served by unprivileged nginx. `/api/`
proxies to `android-manager:8000` on the private Compose network, preserving the
bearer and Origin headers. Docker DNS is refreshed so container replacement does
not pin the proxy to an old backend IP. Browser requests are same-origin; no broad
CORS policy is needed. Routing fallback supports direct device/detail URLs. Proxy
failures return a structured 503 without exposing upstream diagnostics.

Frontend `/frontend-health` checks static serving; backend `/health` checks liveness
and `/ready` checks worker/storage readiness. Frontend health alone does not prove
backend or device availability. Nginx sets basic security headers; plaintext
loopback deployment is not production identity, TLS or authorization hardening.

Before upgrading, use SQLite's backup API inside the private volume for consistent
registry/history backups, and protect these as device inventory. Keep keys and
tokens out of source and logs. After an update verify `/ready`, registered UUIDs,
current freshness, historical points and automatic reconnection. Alerts and rules
persist across restarts; observed device state/capabilities are refreshed.

## M4 upgrade and defaults

M4 adds `security.sqlite3`, `operations.sqlite3` and private `control-artifacts` in
the existing `device-registry` volume; all prior databases, pairing keys, published
ports and Colima networking remain unchanged. Back up all SQLite files consistently
using SQLite's backup API before upgrading. Preserve `.env` and named volumes. Do
not run multiple backend workers: concurrency bounds are per application process.

The existing control token remains administrator; named hashed credentials can be
provisioned through `ANDROID_FLEET_RBAC_CREDENTIALS`. See [authorization](AUTHORIZATION.md).
Missing credentials deny protected API reads and mutations even on loopback.
`ANDROID_FLEET_ANONYMOUS_VIEWER=false` is the M4.5 default; explicit `true` restores
anonymous viewer reads for a deliberately local compatibility workflow. Existing
administrator control tokens still work; the dashboard asks all roles to sign in.

Compose exposes configuration for queue/concurrency/timeouts, APK/screenshot limits,
audit retention (90 days), screenshots (one hour) and resolved alert history (30 days).
Defaults and secret-free examples are in `.env.example`. nginx's upload ceiling is
64 MiB; update it alongside the backend limit if larger uploads are intentionally
supported. API upload time is bounded separately. Protected screenshot previews use
blob URLs allowed by the frontend CSP; their backend URLs are never public assets.

After upgrade, verify named-role denials, queued operation completion, private PNG
delivery and audit/operation persistence across a backend restart. Test only authorized
read-only operations on production hardware. M4 image builds/deployment and actual
hardware acceptance were blocked in this session; [validation](M4_VALIDATION.md)
records the specific unavailable checks instead of claiming deployment success.

## M4.5 coordinated backup and acceptance

Before replacing containers, inspect the actual mounts and create a consistent backup:

```bash
docker-compose ps
docker-compose exec -T android-manager python - < scripts/backup_databases.py
```

The utility writes owner-private timestamped backups and a manifest inside the current
registry volume using SQLite's backup API, verifies integrity and records counts/device
IDs. It records ADB key presence without reading or copying key contents. Stop before
any deployment if backup or integrity verification fails. Each database is a coherent
snapshot; separate files are not one cross-database transaction. Protect manifests as
inventory data. Compare device IDs, retained telemetry, alert rules/events, operation
and audit counts before/after the coordinated backend restart. Do not interpret expected
retention cleanup or additional acceptance events as loss of old records.

[Acceptance evidence](M4_5_VALIDATION.md) distinguishes isolated test persistence from
live volume persistence. Set a private administrator token in the environment and use
`scripts/m4_safe_acceptance.py` only with the verified Samsung device ID; it sends the
four authorized safe actions and never publishes screenshots. It does not install,
uninstall, force-stop or reboot devices. Browser checks must run separately in a real
browser. Never change Colima networking or update unrelated stacks to unblock acceptance.

For future remote access, use a privately reachable HTTPS reverse proxy or authenticated
VPN/proxy arrangement, explicit authenticated reads and firewall rules. Keep the existing
loopback bindings, omit public ADB exposure and test proxy headers/screenshot protection.
The current localhost HTTP is unencrypted; M4.5 does not enable remote access or TLS.

## M5 streaming upgrade

The backend image contains the official scrcpy 3.3.4 server at `/opt/scrcpy/scrcpy-server`, with a build-time SHA-256 check and Apache-2.0 license. No desktop scrcpy renderer, transcoder, privileged container or separate media service is needed. nginx forwards WebSocket upgrades through the existing `/api/` proxy. No ports or existing volume names change. A private `screen-transports.json` manifest in the registry volume supports scoped restart cleanup; it contains transport ownership metadata, not screen frames or bearer credentials.

Compose exposes `ANDROID_FLEET_SCREEN_MAX_SESSIONS` (4), `ANDROID_FLEET_SCREEN_MAX_PER_DEVICE` (2), `ANDROID_FLEET_SCREEN_MAX_PER_USER` (2), `ANDROID_FLEET_SCREEN_IDLE_SECONDS` (30) and `ANDROID_FLEET_SCREEN_ALLOWED_ORIGINS` (JSON array of the two localhost dashboard origins). Backend settings additionally support `ANDROID_FLEET_SCREEN_SERVER_PATH` and `ANDROID_FLEET_SCREEN_QUEUE_FRAMES` (8). Keep one backend worker. Preserve existing `.env`, pairing credentials and volumes; use the coordinated backup procedure above before rebuilding this project's backend/frontend.

After replacement, check `/ready`, existing registry UUIDs and telemetry, then start a view-only session in current Chromium. Stop it and confirm active-session/controller metrics and forwarding cleanup. Live interactive hardware tests require separate explicit authorization. Actual results are in [M5 validation](M5_VALIDATION.md); browser compatibility and transport choices are in [M5 architecture](M5_ARCHITECTURE.md).

## M7 containers

AsyncSSH/cryptography run within the existing backend; Linux PTYs use Python standard
library with the existing ADB binary. No extra published SSH/ADB ports, privileged mode,
Docker socket or key/database volume changes. The existing nginx API upgrade proxy also
serves terminal WebSockets. See [M7 deployment guide](M7_SSH_CONFIGURATION.md).
