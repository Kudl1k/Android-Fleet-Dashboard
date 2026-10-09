# Android Fleet Manager

An early-stage, capability-driven platform for centralized Android monitoring and management through authenticated ADB. Rooted and non-rooted devices share the same platform without a monitoring agent, management APK or SSH server. M0 establishes the foundation; M1 adds persistent registration, discovery and connectivity; M2 adds real monitoring and bounded history; M3 adds the web dashboard and persistent server-side alerting. This is not production-ready infrastructure.

```text
Android devices → authenticated ADB → Android Manager → snapshots → Prometheus → Grafana
React Dashboard → REST → Android Manager → ADB → devices
Android Manager → alert evaluation → SQLite rules/events
```

Rooted devices may use fixed-port TCP ADB and authorized su. Non-rooted devices may use Wireless Debugging/TLS pairing or USB. Connection method does not establish capabilities: bounded probes observe supported operations independently. Battery, CPU, RAM, storage, network, uptime and available thermal monitoring are implemented. Vendor collectors, terminals and arbitrary command execution remain deferred.

## Local development

Install Python 3.13+ and run from the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'backend[dev]'
ANDROID_FLEET_FAKE_ADB=true uvicorn android_fleet.main:app --reload --host 127.0.0.1 --no-proxy-headers
```

Fake mode can seed four registered demo devices: rooted Pixel-like, stock Pixel-like, offline and malformed-output. It contacts no hardware. Set `ANDROID_FLEET_FAKE_ADB=false` to use the configured ADB server; discovered devices require explicit registration. Real registrations receive UUIDs; demo seed IDs preserve M0 serial labels. A SQLite registry preserves stable IDs and connection configuration separately from observed state and capabilities. Manual disconnect disables automatic reconnection until connect or a configuration update enables it again.

Configuration variables are in [.env.example](.env.example). Local Python reads exported environment variables; Compose reads `.env`. Optional mDNS discovery is best effort and associates dynamic connect ports with an exact configured service name. Pairing advertisements remain visible as pairing-required; pairing itself is operator-managed.

Read-only routes include `/health`, `/ready`, `/api/v1/devices`, `/api/v1/discovery/devices` and `/metrics`. Registration, connection and capability-refresh routes are documented in [API conventions](docs/API.md); generated schemas are at `/docs`. Server-side role permissions guard protected reads and controls by default; no tokenless loopback mutations are permitted. See [authorization](docs/AUTHORIZATION.md) for named credentials and optional private reads.

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy src
```

## Docker development

```bash
cp .env.example .env
# Set a Grafana password and a control token before HTTP mutations through Docker.
docker compose config --quiet
docker compose build android-manager frontend
docker compose up -d
```

Use `docker-compose` if the Docker CLI plugin is unavailable. Web dashboard: http://127.0.0.1:8088, Manager: http://127.0.0.1:9000, Prometheus: http://127.0.0.1:9090, Grafana: http://127.0.0.1:1900 (admin and the configured password). A Prometheus datasource and fleet/device dashboards are provisioned in the Android Fleet folder. Volumes preserve the registry, telemetry, alerts, Grafana data and sensitive ADB trust keys. The container registry path is `/var/lib/android-fleet/devices.sqlite3`. Never commit `.env`, registry data or keys.

Docker forwards HTTP from a nonloopback peer, so set `ANDROID_FLEET_CONTROL_TOKEN` for mutation requests even when the published host port is loopback. Network ADB is the deployment assumption. USB passthrough and multicast discovery differ across Linux, macOS Docker Desktop, Colima and Windows; this stack does not provide universal USB passthrough. See [ADB setup](docs/ADB_SETUP.md).

## Continue development

Read [AGENTS.md](AGENTS.md), [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), [API conventions](docs/API.md), [metrics](docs/METRICS.md), [development](docs/DEVELOPMENT.md) and [roadmap](ROADMAP.md) before extending contracts. M4 adds role authorization, persistent audit and bounded device control. M4.5 hardens authenticated reads and session handling; see [M4.5 validation](docs/M4_5_VALIDATION.md) for acceptance limits. Owner license selection is pending; [LICENSE](LICENSE) reserves rights until that decision.

Automated tests need no Android hardware. Production hardening and broader hardware validation remain outstanding. No commits, pushes or GitHub repository creation are performed automatically.

M1 validation: **160 tests passed**, Ruff lint/format and mypy passed, Compose configuration/build and isolated restart/persistence checks passed. See [validation record](docs/M1_VALIDATION.md); real Pixel acceptance remains pending.

M2 adds independent bounded metrics polling, current/history REST endpoints, seven-day/one-million-point SQLite history in the existing private volume, and fleet/device dashboards. See [metrics](docs/METRICS.md) and [M2 validation](docs/M2_VALIDATION.md).

M2 validation: **261 tests passed**, Ruff/mypy and Compose config/build passed. Real non-rooted SM-A356B (registered as “Pixel”) telemetry, Prometheus, dashboard provisioning, registration/history persistence and automatic reconnection after backend restart were verified. Actual Google Pixel and rooted hardware acceptance remain unverified.

M3 provides fleet search/filter/sort, current and historical device pages, authenticated
registration/reconnect management, dark/light themes and alert configuration,
acknowledgement and history. Enter a control token only for the current tab session;
the UI never stores it in browser storage. See [frontend setup](frontend/README.md),
[alert configuration](docs/ALERTING.md), [deployment](docs/DOCKER.md) and
[M3 validation](docs/M3_VALIDATION.md) for actual checks and acceptance limits.
