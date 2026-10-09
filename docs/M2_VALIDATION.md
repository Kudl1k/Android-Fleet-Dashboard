# M2 implementation and validation — 2026-10-09

M2 adds modular ADB battery, interval CPU/per-core frequency, RAM/swap, `/data` storage, interface byte counters, uptime and available thermal collectors. Commands are read-only and baseline collection does not require root. Normalized partial snapshots feed current APIs, separate SQLite history and Prometheus; HTTP reads never execute ADB commands.

Three specialized agents implemented collectors/fixtures, history/API models/lifecycle tests, and Prometheus/Grafana/API tests. The coordinator owned shared contracts, scheduling, integration, infrastructure and acceptance. Existing registry files, key volumes, ports and unrelated Docker stacks were preserved. A SQLite backup was created in the private registry volume before the backend update. No commits or pushes were made.

## Automated and Docker checks

From repository root, using the Python 3.13 virtual environment:

```bash
.venv/bin/pytest backend/tests -q
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/mypy backend/src
docker-compose config --quiet
docker-compose build android-manager
```

Tests cover recorded outputs, rooted/non-rooted fake devices, malformed and denied sources, CPU warmup/reset, reconnect/disconnect generation invalidation, per-device timeout partial results, independent connectivity polling, concurrent history access, retention, restart persistence, pagination and graceful shutdown. All existing M0/M1 tests remain included. Final totals are recorded below after integration.

Compose configuration and backend build succeeded. The host lacks buildx, so Compose used its working legacy builder. Only this project's backend and Grafana were recreated; Colima, networking, Komodo and unrelated stacks were not changed. Backend liveness/readiness, Prometheus queries and Grafana provisioning were checked. Dashboard API lists Android Fleet Overview (`android-fleet-overview`) and Android Device Detail (`android-fleet-device`). Ports remain localhost 9000, 9090 and 1900.

## Actual hardware acceptance

The existing registration is named **Pixel**, but safe probing identifies its actual model as **Samsung SM-A356B**, Android **16**, with **root unavailable**. This is successful real non-rooted Android acceptance, not verified Google Pixel hardware acceptance.

Wireless Debugging authorization and reconnect worked through the container-owned ADB server on Colima. The operator supplied changed connection ports; authenticated PATCH updated the existing registration without changing its UUID. Pairing credentials were not persisted in source, registry or documentation. Transient refused ports left the backend healthy and the device visibly offline.

Actual current API and local history showed battery, aggregate/per-core CPU after warmup, CPU frequency, RAM/swap, network byte counters, uptime and seven live HAL temperatures/status. Representative observations: battery ratio 0.68, battery temperature 32.5 Celsius, RAM total 5,689,376,768 bytes; values naturally change. Prometheus queries returned live CPU, RAM and thermal series. History contained observations from successive polling cycles.

Hardware revealed `/data` binding to `/data/user/0` and numerous inactive virtual network interfaces. Regression fixtures cover the bind mount; bounded selection prioritizes active/physical interfaces so Wi-Fi is retained. Final storage/Wi-Fi and restart checks are recorded below.

## Limits and follow-up

Actual rooted hardware, a Google Pixel, other OEM/Android versions, permission-denied fallbacks on hardware, multicast discovery and changing ports without manual input are unverified. Automated fake/fixture tests cover supported failures and rooted cases. Optional battery current and individual thermal/frequency sources remain unavailable when denied or unsupported. Thermal status is severity, not proof of throttling. No GPU/NPU/DSP metrics are implemented.

History defaults to seven days and one million individual points globally; eviction can occur sooner at capacity. SQLite reuses allocated pages and does not promise secure erasure/file shrinkage. Prometheus remains separate historical storage. Read APIs are unauthenticated and loopback deployment remains required until access controls are hardened. Grafana dashboards were provisioned and data queries checked; visual browser review and alerting remain M3 work.

## Final results

**261 tests passed**, Ruff lint and formatting passed (56 Python files), and mypy passed (41 source files). Compose configuration and final image build passed. After final backend recreation, all five existing registered IDs were preserved, the real device automatically returned online using persistent pairing keys, and prior CPU historical points remained queryable. Fresh storage values were 113,105,678,336 total bytes, with used/free values; `wlan0` receive/transmit counters were present. Backend `/health` and `/ready` returned 200. Live Prometheus core/thermal queries and both Grafana dashboard definitions were verified.
