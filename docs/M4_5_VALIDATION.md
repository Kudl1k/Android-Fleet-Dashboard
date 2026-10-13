# M4.5 deployment, hardening and acceptance — 2026-10-09

**M4.5 is ready to close; M5 can begin within the existing local-only boundary.**
Runtime continuation at 19:55–20:03 UTC completed the previously blocked deployment,
safe Samsung, Chromium and recovery checks. Earlier sandbox failures are historical,
not the current environment. This is foundation/homelab acceptance, not production
or broad OEM/rooted hardware certification. No M4 implementation was repeated.

## Preflight and preservation

| Check | Status | Actual evidence |
| --- | --- | --- |
| Git branch/tree | PASS | Existing `main`, commit `2ba42d3`; clean tree before continuation. No commit or push performed. |
| Docker / Colima | PASS | Docker server 29.5.2; Colima running, aarch64, macOS Virtualization.Framework. Existing context/settings retained. |
| Local HTTP | PASS | Backend `/health` and `/ready`, frontend `/frontend-health`, Prometheus `/-/ready`, Grafana `/api/health`: final HTTP 200. |
| GitHub DNS/network | PASS | `getaddrinfo('github.com', 443)` returned two records; HTTPS GET to GitHub returned 200. SSH authentication/publication not attempted. |
| ADB connectivity | PASS | Host server has no attached devices; backend server sees authenticated wireless Samsung SM-A356B. Host enumeration started a local ADB daemon; no public ADB port was introduced. |
| Actual mounts | PASS | `adb-dashboard_adb-keys` → `/home/fleet/.android`; `adb-dashboard_device-registry` → `/var/lib/android-fleet`. Both RSA key files present before/after recreation; contents never printed. |
| Consistent backup before deployment | PASS | SQLite backup API; all four existing snapshots `integrity: ok`. Private volume backup `20261009T195558Z-fe9c2bce55f14964861de424fe124265`; copied to `/private/tmp/m45-runtime/predeployment-backup`, independently integrity-checked on host. |
| Baseline / preservation | PASS | Five registrations, eight rules, four events, 64,753 samples; operations/security databases absent before M4 deployment. Final verified snapshot: five registrations, eight rules, five events, 66,262 samples, six completed operations, 145 audit rows. |
| Deployment | PASS | Build and recreation limited to `android-manager` and `frontend`, using `--no-deps`; no volume deletion, Colima change, public exposure or unrelated-stack change. |

Preservation compared registration configuration fields, rule rows, stable event fields,
all baseline telemetry rows, and completed operation/audit rows against consistent
backups. Zero missing baseline rows. Reconnect timestamps and evaluated event state/body
may change normally; they were not treated as lost records. Final six-database integrity
backup also copied outside Docker: `/private/tmp/m45-runtime/final-backup`.
The existing `.env` was not edited. Temporary acceptance role hashes were added through
a private Compose override, preserving existing credentials. Screenshot retention was
120 seconds during acceptance and restored to 3600 seconds. Temporary credentials are
revoked, original administrator works, anonymous reads remain disabled.

## Previously completed automated results

| Check | Status | Result |
| --- | --- | --- |
| Backend suite | PASS | **379 passed**, including M0–M3 and new hardening/utility tests. |
| Ruff backend lint/format | PASS | 73 Python files already formatted. |
| Backend mypy | PASS | Strict check of 50 source files. |
| Acceptance utility Ruff/mypy | PASS | Two scripts, backend configuration and strict typing. |
| Frontend suite | PASS | **45 tests in 9 files**. |
| Frontend lint/typecheck/build | PASS | ESLint, TypeScript and production Vite build exit zero. |
| Compose config | PASS | Configuration validates with unchanged ports/services. |
| Backend/frontend Docker images | PASS | Runtime continuation built both images successfully; see deployment evidence. |
| Hosted CI | NOT RUN | No successful GitHub push; local checks do not establish hosted CI success. |

The following checks passed in the preceding M4.5 work and were not unnecessarily rerun.
This continuation changed documentation only; image builds reran the frontend production build.

Previously executed commands (including the then-blocked image-build attempts):

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
| Real deployed role matrix | PASS | Actual deployed unauthenticated/invalid/viewer/operator/administrator read, history, audit, management authorization, APK denial and protected screenshot checks passed. Mutation authorization used a nonexistent device or denied role to avoid hardware effects. |
| Monitoring exposure | PASS | Configuration/review verified local/trusted-network exception. `/metrics` and Prometheus queries remain unauthenticated and expose telemetry/device IDs; no claim of blanket data authentication. |

Local HTTP is unencrypted. No remote access or TLS termination was introduced. Future
remote ingress should use a private authenticated HTTPS proxy/VPN, restrict monitoring
routes and ports, preserve authenticated API reads and never expose ADB. Roles remain
fleet-wide; token expiry/revocation infrastructure, per-device scopes, immutable external
audit, rate limiting and dependency/image locking remain future hardening.

## Runtime acceptance

| Required check | Status | Actual evidence |
| --- | --- | --- |
| Deployed backend/frontend health/readiness | PASS | Both application containers healthy; final HTTP 200 at actual health endpoints. Image IDs: backend `6d190cf6bae6`, frontend `f8257650f63a`. |
| Monitoring | PASS | Prometheus target `android-manager:8000` up, no scrape error; query `up` = 1. Grafana 11.6.0 health OK; authenticated datasource health says successfully queried Prometheus API. Monitoring containers were not recreated/restarted. |
| Role authentication/authorization | PASS | Missing/invalid tokens: 401. All three roles read fleet/history; viewer/operator audit denied 403, administrator audit 200. Viewer inspect denied 403. Viewer/operator APK and device-management denied 403; administrator missing-device management reaches 404. |
| Audit/history/persistence | PASS | Four safe operations present in history with matching successful audit records. Denials audited. Pre-restart six operations and 67 audit rows preserved exactly; final verified snapshot has 145 audit rows; subsequent checks may append more. |
| Samsung state/properties/apps.list/screenshot | PASS | All four actual API jobs succeeded; recorded transitions/history/audit verified. Samsung is the existing registration named `Pixel`, not Google Pixel hardware. |
| Protected PNG | PASS | 1080×2340, 180,753 bytes, PNG chunk framing/CRC valid; unauthenticated 401, viewer 403, operator/administrator 200; `no-store` and `nosniff`. Pixels not published. |
| Actual screenshot expiry/cleanup | PASS | Initial screenshot naturally aged beyond temporary 120-second retention: HTTP 404 at 152.3 seconds; corresponding artifact absent, history retained. Normal 3600-second configuration restored; full one-hour retention was not waited out. |
| Chromium desktop/mobile | PASS | Chromium 156.0.8078.4, 1440×1000 and 390×844. Fleet/detail/control, package search, protected previews, operation/audit filters, alerts/management, role controls, cancelled confirmation, offline, loading/error, memory-only credentials and actual credential revocation passed. |
| Backend restart recovery | PASS | `docker-compose restart android-manager`: readiness 200, Samsung online, preserved registrations/rules/events/telemetry/operations/audit. No job replay. |
| Container recreation / ADB trust | PASS | Final clean `up -d --no-deps --force-recreate android-manager` automatically reached Samsung online/readiness in 3.1 seconds without manual ADB intervention. RSA trust persisted; no pairing code needed. |
| Offline/timeout/failure fixtures | PASS | Previously completed isolated tests retained. Actual browser also verified existing offline registration; hardware was not deliberately disconnected. |
| Hardware timeout/failure or destructive actions | NOT RUN | No reboot, recovery/bootloader, install/uninstall, force-stop, wake/lock or arbitrary shell acceptance performed. Broader rooted/OEM hardware remains unverified. |

One configuration-restoration recreation remained offline at a 30-second deadline.
A diagnostic connection through `SubprocessAdbClient` succeeded with preserved trust.
The subsequent clean recreation above passed automatically. This transient is recorded;
the failed deadline was not silently counted as a pass. Browser harness retries corrected
a hidden-option selector and hard-navigation credential clearing; final assertions passed.
Browser diagnostics contain expected HTTP 401 for sign-out/revocation and 503 for offline
telemetry, zero JavaScript page errors, and no unexpected network failures.

See [deployment evidence](M4_5_DEPLOYMENT.md), [browser evidence](M4_5_BROWSER.md)
and [hardware evidence](M4_5_HARDWARE.md). Private runtime manifests, sanitized JSON
results and browser screenshots live under `/private/tmp/m45-runtime` (directory 0700).
They are local evidence, excluded from Git; temporary credentials are revoked. Browser
screenshots exclude the protected screen preview. No screenshot pixels were published.

## Publication and M5

No commits, pushes or repository creation were performed in this continuation. GitHub
DNS/HTTPS access now works; this does not establish SSH authentication, remote contents,
publication or hosted CI success. Prior failed publication is not retried under this request.

Verified local URLs: frontend **http://127.0.0.1:8088**, backend
**http://127.0.0.1:9000**, Grafana **http://127.0.0.1:1900**, Prometheus
**http://127.0.0.1:9090**. Ports remain loopback-only; no published 5037.

M4.5 acceptance is complete for the approved safe scope. M5 may start by designing
per-device interaction permissions, authenticated bounded streaming with cancellation
and backpressure, and private HTTPS ingress. Remote deployment, production load/soak,
broader OEM/rooted hardware and destructive control acceptance are separate future work.
