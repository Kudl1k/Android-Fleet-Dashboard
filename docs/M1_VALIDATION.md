# M1 validation — 2026-10-09

## Result

Software implementation is complete and automated checks pass. Hardware acceptance remains pending: no Android phone was available or contacted, no TLS pairing was performed, and cross-VM multicast/USB was not verified. M2 was not started.

Baseline: Python 3.13.16; all 40 M0 tests, Ruff lint/format and mypy passed before changes. Existing backend readiness returned 200. The directory lacked Git; it was initialized locally without commit, remote, push or GitHub repository creation.

Final commands (from backend, using the repository .venv):

| Check | Result |
| --- | --- |
| pytest | 160 passed: existing 40 plus 120 additional cases |
| ruff check . | Passed |
| ruff format --check . | Passed; 41 Python files |
| mypy src | Passed; 31 source files |
| docker-compose config --quiet (repository root) | Passed |
| docker-compose build (repository root) | Passed using legacy builder; buildx warning is nonfatal |

Hosted CI was not run. Android vendor metrics, real hardware connectivity and full production authentication are not validated by these results.

## Runtime validation

An isolated, uniquely named smoke container used no published ports and network=none, with its own database/key volumes and a temporary control token. It verified registration, stable UUID, observed fake-device capabilities, metrics omission after disconnect, disconnect intent across restart, and SQLite persistence after removing/recreating the container. Real-mode startup verified the included ADB server could initialize its keys and report readiness with zero attached phones; an unavailable registered USB serial stayed offline. No device was reported online merely from the database.

The original running container ID inventory was checked before/after. Komodo, unrelated services and the existing manager/Grafana/Prometheus containers were not restarted, removed or recreated. Existing loopback ports remain 9000, 1900 and 9090. Only isolated smoke resources were cleaned up. The built M1 image is ready for an operator-controlled backend rollout; the running backend was intentionally left on its original image during validation.

## Architecture and persistence

Default ADB server ownership is container-local, with private persisted keys and no published 5037. mDNS auto-connect is disabled so the manager controls connection intent. Bridged discovery is optional; IP/connection port registration remains the fallback. Uvicorn proxy-header rewriting is disabled in supported commands. See ARCHITECTURE.md, ADB_SETUP.md and SECURITY.md.

SQLite v1 stores id, name, connection_type, host, port, serial, mdns_service, normalized unique endpoint, JSON string metadata, auto_connect, created_at, updated_at and last_connected_at. UUIDs are independent of transport/port; demo seed IDs retain M0 labels. Endpoint, USB serial and mDNS service uniqueness is enforced transactionally. Operational states/capabilities/metrics and private keys are never stored there.

Validation includes concurrent initialization/access, duplicates, restart persistence, canceled SQLite operations, merged concurrent PATCH requests, rooted/non-rooted observations, unauthorized/offline transports, timeouts, bounded jitter/backoff, duplicate connect prevention, dynamic ports, malformed mDNS, missing capabilities, shutdown/startup cancellation, stale metrics and direct-peer/token guards.

## File manifest

| Change | Files |
| --- | --- |
| New configuration/storage | backend/src/android_fleet/devices/registry_models.py, registry.py |
| New connection orchestration | backend/src/android_fleet/adb/connection_models.py, connection.py |
| New discovery | backend/src/android_fleet/discovery/__init__.py, models.py, service.py |
| New mutation guard | backend/src/android_fleet/api/security.py |
| Updated adapters | backend/src/android_fleet/adb/base.py, fake.py, subprocess.py |
| Updated runtime/integration | backend/src/android_fleet/devices/models.py, probe.py, service.py; backend/src/android_fleet/main.py; api/models.py; core/settings.py |
| New tests | backend/tests/conftest.py, test_registry.py, test_connection.py, test_discovery.py, test_m1_api.py |
| Expanded tests | backend/tests/test_adb.py, test_probe.py |
| Infrastructure/config | backend/pyproject.toml, docker/Dockerfile, docker-compose.yml, .env.example, .gitignore |
| Documentation | README.md, ROADMAP.md, docs/ARCHITECTURE.md, ADB_SETUP.md, API.md, SECURITY.md, DEVELOPMENT.md, M1_VALIDATION.md |

## Remaining acceptance work

Connect an actual Pixel using the documented container pairing and registration steps. Verify authorization/unauthorized behavior on its Android version, real TCP reachability, root policy when applicable and reconnect after Wi-Fi interruptions. Test exact mDNS identity/dynamic ports where multicast is supported; otherwise maintain the manual fallback. Native USB/host-server deployments need their own secured routing validation. One backend worker is supported; large fleets and distributed schedulers remain future work. Production RBAC, TLS, audit logs, dependency locking and vendor metrics remain out of scope.
