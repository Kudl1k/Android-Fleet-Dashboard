# Development

Use Python 3.13+. From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'backend[dev]'
pre-commit install
ANDROID_FLEET_FAKE_ADB=true uvicorn android_fleet.main:app --reload --host 127.0.0.1 --no-proxy-headers
```

The pre-commit hook requires initialized Git. Do not commit or push automatically. Settings read environment variables; Compose reads `.env`, local Python does not. Fake mode is the default and never proves real connectivity. Set `ANDROID_FLEET_FAKE_ADB=false` and install Android platform-tools to use real ADB. Set `ANDROID_FLEET_CONTROL_TOKEN` when requests reach the backend from a nonloopback peer, including Docker forwarding.

`ANDROID_FLEET_SEED_FAKE_DEVICES=true` seeds demo registry entries only in fake mode. Stable UUID registrations are stored in SQLite; observations and capabilities are refreshed separately. Compose persists `/var/lib/android-fleet/devices.sqlite3` in a data volume. For isolated experiments, set `ANDROID_FLEET_REGISTRY_PATH` to a separate database; its local default is `data/devices.sqlite3`. Real transports are not automatically registered. Set `ANDROID_FLEET_MDNS=true` to enable best-effort mDNS discovery; it may not work across container network boundaries.

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy src
# Optional fixes:
ruff check --fix .
ruff format .
```

Tests use fake ADB, recorded command fixtures, temporary SQLite registries and injected subprocess mocks. Timeout tests launch only short-lived local processes. ASGI tests explicitly enter FastAPI lifespan and should inject isolated configuration/storage. Test registry lifecycle, exact service association, unavailable mDNS, reconnect state transitions, mutation guards, parser malformed output, and rooted/non-rooted capability observations without hardware or privileged host access. No real Android hardware validation is claimed.

## Collaboration

Read AGENTS.md before work. A coordinator owns shared interfaces, delegates bounded modules with expected files and acceptance criteria, and integrates reported interface changes. Inspect existing contracts before adding methods. Domain models do not import FastAPI; collectors do not import Prometheus; API code does not spawn processes. Persistence adapters and API validation produce domain configuration models. Vendor implementations use explicit collector applicability interfaces. Avoid unused scaffolding and dependencies.

Connection state and capabilities have separate lifecycles. Reconnects invalidate stale observations; unsupported metrics remain absent. Discovery must not mutate registration or silently pair/connect devices. Do not change exact service matching into broad host matching. Connection and polling tasks must cancel cleanly on application shutdown.

Dependencies are declared in pyproject.toml; there is no dependency lock. Before production, resolve and review exact dependencies, supported image patches and image digests. CI uses Python 3.13 for pytest, Ruff and mypy, and checks Compose configuration and the backend image build. Local passing checks do not establish that a hosted workflow ran.

## Infrastructure checks

```bash
# From repository root, after configuring .env:
docker compose config --quiet
docker compose build android-manager
docker compose up -d
```

The standalone `docker-compose` executable is an equivalent fallback when the CLI plugin is unavailable. Host ports are manager 9000, Grafana 1900 and Prometheus 9090, bound to loopback. Configure a control token before attempting HTTP mutations through Docker. A tokenless direct local development server permits mutation only from loopback without an Origin header. Read-only monitoring is unauthenticated.

Network ADB is the initial deployment assumption. USB passthrough differs across Linux, Docker Desktop, Colima and Windows; do not add privileged mode as a generic workaround. See ADB_SETUP.md for host-server and pairing guidance. Protect registry data, ADB keys and `.env`; none belong in Git.

## Validation reporting

Record actual commands and results when completing a milestone. Python 3.13 and the local virtual environment are now available; prior environment blockers are not the current validation record. Required acceptance checks are pytest, Ruff lint, Ruff format, mypy, Compose config and an image build where the daemon is available. Report unavailable checks explicitly. Hardware, USB, multicast discovery, hosted workflow execution and production deployment require separate validation; tests using fake ADB do not establish those behaviors.

The final M1 baseline/results, changed files and hardware limitations are recorded in [M1 validation](M1_VALIDATION.md).

M2 tests cover collector fixture parsing, permission failures, CPU warmup/reset, malformed sources, history persistence/retention/concurrency/cursors, API freshness and lifecycle cancellation. The history store can be injected with `:memory:` for tests. Collection settings are listed in `.env.example`; local runs use exported environment variables. Do not point history storage at the device registry file. Compose shares the existing private volume while keeping separate database files.

## M3 frontend and alerts

Node 22+ is required. From `frontend`, run `npm ci`, `npm run lint`,
`npm run typecheck`, `npm test` and `npm run build`; `npm run dev` proxies API
requests to localhost:9000. See [frontend setup](../frontend/README.md).
CI now checks both applications and builds both production images; hosted CI was
not invoked during local milestone acceptance. Update this stack with scoped
`docker-compose up -d --no-deps android-manager frontend`, preserving volumes.
The dashboard uses localhost:8088 alongside the unchanged monitoring ports.

Alert tests use isolated SQLite stores and deterministic evaluation times. They
cover hysteresis, sustained windows, deduplication, acknowledgement/recovery,
per-device overrides, migration/restart persistence, authentication, invalid and
unsupported observations, and disconnect/reconnect generations. Browser smoke
checks complement component tests; see [M3 validation](M3_VALIDATION.md).
