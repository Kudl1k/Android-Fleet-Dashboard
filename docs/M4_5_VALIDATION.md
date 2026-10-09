# M4.5 deployment, hardening and acceptance — 2026-10-09

**M4.5 is incomplete.** Static and isolated automated checks passed; deployed acceptance
could not run. The user reported full access; a subsequent retry and direct probes still
returned operating-system sandbox errors. No mocked check is counted as deployed,
browser or Samsung acceptance.

## Preflight and preservation

| Check | Status | Actual evidence |
| --- | --- | --- |
| Git branch and tree | PASS | Preflight branch `main`, unborn (no commits), project files untracked; no existing history replaced. |
| Compose availability/configuration | PASS | `docker-compose config --quiet` exits zero; sanitized parsed configuration inspected. |
| Docker / running project containers | BLOCKED | `docker-compose ps`, `docker info --format '{{.ServerVersion}}'` deny access to `/Users/homelab/.colima/default/docker.sock`. Direct AF_UNIX connection returns errno 1 `Operation not permitted`. |
| Colima state | BLOCKED | `colima status` exits with `colima is not running`; actual daemon state cannot be established under these restrictions. No restart/network change attempted. |
| Backend / frontend / monitoring reachability | BLOCKED | curl exit 7, HTTP 000 for backend health/readiness, frontend health, Prometheus readiness and Grafana health. Direct ephemeral loopback bind returns errno 1 `Operation not permitted`. |
| Declared ports/volumes | PASS | Compose has loopback 8088/9000/1900/9090; no published 5037. Existing registry/key/Prometheus/Grafana volume names retained. This verifies declaration only. |
| Actual mounts / database paths / active record counts | BLOCKED | Container inspection unavailable; current registered identifiers and device/alert/audit/operation counts are unknown. Historical M3 counts were not substituted. |
| Active consistent backup and integrity | BLOCKED | Cannot access active databases through Docker. No container replacement/migration allowed without verified backup. |
| ADB pairing credentials and Samsung connection | BLOCKED | Actual container filesystem/server unavailable; neither key persistence nor Samsung connection observed. |

The existing `.env` was not edited and no secrets were printed. Resolved Compose
configuration reports anonymous viewer access false and an existing legacy administrator
token configured (boolean only). No volumes, databases, pairing keys, unrelated services,
published ports or Colima configuration were changed.

## Fresh automated results

| Check | Status | Result |
| --- | --- | --- |
| Backend suite | PASS | **379 passed**, including M0–M3 and new hardening/utility tests. |
| Ruff backend lint/format | PASS | 73 Python files already formatted. |
| Backend mypy | PASS | Strict check of 50 source files. |
| Acceptance utility Ruff/mypy | PASS | Two scripts, backend configuration and strict typing. |
| Frontend suite | PASS | **45 tests in 9 files**. |
| Frontend lint/typecheck/build | PASS | ESLint, TypeScript and production Vite build exit zero. |
| Compose config | PASS | Configuration validates with unchanged ports/services. |
| Backend/frontend Docker images | BLOCKED | Normal and `DOCKER_BUILDKIT=0 COMPOSE_BAKE=false` builds cannot connect to Docker socket. No new image ID or build success reported. |
| Hosted CI | NOT RUN | No successful GitHub push; local checks do not establish hosted CI success. |

Executed commands:

```bash
.venv/bin/pytest backend/tests -q
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/mypy backend/src
.venv/bin/ruff check --config backend/pyproject.toml scripts
.venv/bin/ruff format --config backend/pyproject.toml --check scripts
.venv/bin/mypy --config-file backend/pyproject.toml scripts
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
# Repository root:
docker-compose config --quiet
docker-compose build android-manager frontend
DOCKER_BUILDKIT=0 COMPOSE_BAKE=false docker-compose build android-manager frontend
```

One existing Starlette TestClient/httpx deprecation warning remains. New tests cover
secure defaults, four route-word identifier bypasses, stale/expired token responses,
preview revocation, consistent WAL backups, corrupt/symlink database refusal,
private backup permissions, bounded safe acceptance inputs, delayed audit appends,
PNG framing/CRCs and private local-only HTTP transport.

## Security findings and fixes

| Finding/check | Status | Result |
| --- | --- | --- |
| Device identifier middleware bypass | PASS | Fixed substring exclusions that let device IDs containing `audit`, `operations`, `apk` or `auth` evade authentication. Exclusions now match complete control route shapes; four regressions pass. |
| Insecure anonymous API default | PASS | Settings, security service, Compose and example default false. Legacy anonymous workflow requires explicit true; existing tokens retain administrator compatibility. Tests opt in explicitly where they exercise that workflow. |
| Expired/stale browser authentication | PASS | Active-token 401 clears credentials/identity/cache. Successful responses from superseded credentials are rejected; screenshot previews and confirmations reset on credential/device changes. Component tests verify this. |
| Protected screenshots/APK/package controls | PASS | Isolated backend tests verify role checks, private PNG/no-store delivery, size/retention, upload/type/structure limits and protected-package refusal. These are not Samsung acceptance. |
| CORS/output/errors | PASS | Static inspection and regression checks: same-origin proxy, no permissive CORS, bounded argv/output, fixed sanitized errors and no arbitrary shell API. |
| Real deployed role matrix | BLOCKED | Unauthenticated/viewer/operator/administrator reads, device management, APK, audit/history and screenshot checks need live M4 deployment. |
| Monitoring exposure | PASS | Configuration/review verified local/trusted-network exception. `/metrics` and Prometheus queries remain unauthenticated and expose telemetry/device IDs; no claim of blanket data authentication. |

Local HTTP is unencrypted. No remote access or TLS termination was introduced. Future
remote ingress should use a private authenticated HTTPS proxy/VPN, restrict monitoring
routes and ports, preserve authenticated API reads and never expose ADB. Roles remain
fleet-wide; token expiry/revocation infrastructure, per-device scopes, immutable external
audit, rate limiting and dependency/image locking remain future hardening.

## Runtime acceptance

| Required check | Status | Reason |
| --- | --- | --- |
| Deploy updated backend/frontend; health/readiness | BLOCKED | No Docker access or verified active database backup. |
| Prometheus scrape/Grafana health after deployment | BLOCKED | Runtime sockets unavailable. |
| Active migration / registration / telemetry / alert / audit / operation preservation | BLOCKED | Actual database baselines and controlled restart unavailable. Isolated restart tests passed separately. |
| ADB trust after recreation / Samsung reconnect | BLOCKED | No container/server access; no key contents read/copied. |
| Samsung approved properties, packages, state, screenshot | BLOCKED | Backend unreachable; **zero hardware operations performed**. |
| Samsung screenshot authorization, PNG, retention/cleanup | BLOCKED | No actual capture exists; utility/unit tests do not prove runtime capture or expiry. |
| Offline/timeout/failure fixtures | PASS | Isolated fake operation tests pass; no hardware evidence implied. |
| Hardware timeout/failure probing | NOT RUN | Backend unavailable; no attempt to disrupt Samsung for failure acceptance. |
| Actual desktop/mobile browser scenarios | BLOCKED | Headless Chromium fails MachPortRendezvous bootstrap IPC permission 1100/SIGTRAP; full Chromium fails SIGABRT before navigation. No browser session ran. |
| Reboot/install/uninstall/force-stop/recovery/bootloader on Samsung | NOT RUN | Explicitly prohibited by this acceptance request; no arbitrary ADB shell issued. |

See [deployment evidence](M4_5_DEPLOYMENT.md), [browser evidence](M4_5_BROWSER.md) and
[hardware evidence](M4_5_HARDWARE.md). The safe CLI sends only `state`, `properties`,
`apps.list`, `screenshot`, polls operation/history/audit and validates PNG framing without
printing or publishing pixels. It requires an environment token and explicit device ID.
The backup utility creates timestamped private SQLite snapshots and verifies integrity;
it has not been run against active volumes.

## Publication and next steps

The user explicitly authorized publication to
`git@github.com:Kudl1k/Android-Fleet-Dashboard.git`. `origin` is configured accordingly.
A local root commit was created after staged-file secret/artifact checks (169 source
files, no private-file/token-pattern violations). `git push -u origin main` is
**BLOCKED**: SSH cannot resolve `github.com`. A read-only HTTPS fallback
`GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/Kudl1k/Android-Fleet-Dashboard.git`
also fails DNS resolution. No successful push or remote repository contents are verified.
Publication excludes environment files,
keys, databases/sidecars, APKs, backups, node_modules/build output and private artifacts.

Expected deployment URLs remain frontend **http://127.0.0.1:8088**, backend
**http://127.0.0.1:9000**, Grafana **http://127.0.0.1:1900**, Prometheus
**http://127.0.0.1:9090**; they are not verified reachable in this session.

Restore execution access, inspect actual mounts, run/verify the consistent backup and
baseline counts, then build/recreate only backend/frontend. Verify deployed role matrix,
monitoring, four safe Samsung actions, protected screenshot expiration, desktop/mobile
browser scenarios and controlled backend restart/reconnect. Only then close M4/M4.5.
M5 prerequisites are this runtime acceptance plus scoped per-device interaction permissions,
authenticated bounded streaming/backpressure and a private HTTPS deployment design.
