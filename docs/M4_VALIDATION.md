# M4 implementation and validation — 2026-10-09

M4 code is implemented and locally validated. Full milestone acceptance remains
pending: this session cannot access the deployment Docker socket or live backend,
and Chromium cannot launch under its sandbox. No deployment or Samsung control
success is claimed. No commits or pushes were made.

## Implementation

Three parallel agents owned authorization/audit, ADB operations and frontend files.
The lead agreed shared action/permission/API contracts, integrated lifespan and existing
API protections, reviewed security with the authorization agent, added reliability
and integration tests, updated Docker settings/documentation and ran final checks.
No overlapping module edits were used during parallel implementation.

The backend supplies operation-level role permissions, named high-entropy bearer
credential hashes, legacy administrator token compatibility and optional anonymous
viewer reads. All existing device/telemetry/alert APIs and new control/history/artifact
APIs enforce server permissions; no tokenless loopback control exemption remains.
[Authorization](AUTHORIZATION.md) documents provisioning and the exact matrix.

Persistent `security.sqlite3` audit entries include actor/role, action, device,
request/operation ID, allowed/denied decision, outcome, duration and fixed sanitized
error codes. Rejected privileged requests and restart recovery outcomes are audited.
Updates are blocked by a database trigger; no public mutation routes exist. Startup
and minute maintenance enforce configurable 90-day retention.

Persistent `operations.sqlite3` tracks queued/running/succeeded/failed/cancelled/timed_out
records. Four global jobs, one per device and 100 outstanding jobs are defaults. Per-action
execution deadlines, bounded text output, private artifacts and safe owner-aware
cancellation are implemented. Restart fails interrupted work without replay. APK
uploads have streaming size/deadline/concurrency bounds, ZIP and binary XML structure
checks, generated private filenames and cleanup. Android validates final APK signing.
Protected screenshot downloads have PNG checks, size/retention bounds and no-store headers.

Device Control includes properties/state, packages/search/metadata, launch/confirmed
force-stop, APK installation progress, confirmed uninstall/reboot, sleep/wake and
protected screenshot preview/download. Operations and administrator Audit pages have
filters, pagination and sanitized results. Existing management/alerts now gate controls
using server-provided permissions; credentials remain in memory. No optimistic device
success is shown from queue acceptance. [Device control](DEVICE_CONTROL.md) records
supported actions and result semantics.

Resolved alert history expires after a configurable 30 days; active incidents survive
cleanup. Evaluation health/count/error/duration/timestamp metrics and prolonged-offline,
repeated-reconnect/deduplication tests extend M3 without external notification delivery.

## Automated checks

Commands from the repository:

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
# From repository root:
docker-compose config --quiet
```

Final backend result: **351 tests passed**, including all M0–M3 coverage. Ruff lint and formatting pass for 71 Python files, and strict mypy passes for
50 source files. Frontend ESLint/typecheck, **41 tests in 9 files**, and the
production build pass. One existing Starlette TestClient/httpx deprecation
warning remains. Production frontend build and Compose configuration pass.

Coverage includes every role/permission, unknown permissions, credential substitution, reserved-actor aliases
and malformed tokens, existing endpoint protections, persisted/filtered audits,
strict destructive confirmations and correlated validation failures, job states,
global/per-device concurrency, deadlines/cancellation, owner checks, restart/no replay,
invalid packages, shell/path injection, malformed/oversized APKs, system-package
protection, private screenshot access/expiry/size/signature, offline and unsupported
operations, persistence/schema safeguards and real bounded subprocess kill/drain/reap.
Frontend tests cover permission states, confirmations, authenticated screenshot requests,
existing M3 behavior and the new Operations/Audit pages.

## Deployment and persistence

Compose configuration confirms unchanged loopback ports **8088, 9000, 1900, 9090**,
no published ADB 5037, and unchanged named registry/key/monitoring volumes. New audit,
operation and private capture storage lives in the existing registry volume. The
frontend proxy now accepts the default 64 MiB APK limit and protected blob previews.
Only example/configuration files were changed; existing `.env`, Docker volumes,
registry records, pairing keys and Colima networking were not modified.

`docker-compose build android-manager frontend` was attempted and rejected with
permission denied connecting to `/Users/homelab/.colima/default/docker.sock`.
The CLI also reports missing buildx. No services were recreated or restarted; neither
image build nor live deployment/persistence acceptance is verified. A live backend
request to `127.0.0.1:9000` failed to connect from this session. Automated restart
persistence tests pass using isolated SQLite databases; these do not establish live
volume acceptance.

## Browser and real-device acceptance

Installed Chromium/Playwright was attempted. Chromium failed before navigation with
MachPortRendezvousServer `bootstrap_check_in: Permission denied (1100)` and SIGTRAP.
Desktop/mobile visual, keyboard and production-browser acceptance remain unverified.
See [browser evidence](M4_BROWSER.md); component tests are not browser acceptance.

The previously monitored registration named Pixel is Samsung SM-A356B, Android 16,
non-rooted, as documented by M2/M3. This session did not reach its container-owned
ADB server. **No M4 real-device state, property, package-list or screenshot operation
was verified.** No reboot, recovery/bootloader action, install, uninstall or force-stop
was attempted on hardware. Fake acceptance never counts as destructive hardware acceptance.

Once runtime access is available, back up existing SQLite files inside the private
volume, build/recreate only backend/frontend, verify prior registrations/history,
then run the four authorized safe Samsung actions through the authenticated operation
API. Confirm protected screenshot access, persistent operation/audit history after
backend restart, automatic reconnect, monitoring freshness and desktop/mobile UI.
Do not perform hardware mutations without explicit approval.

## Security limits and M5

The deployment remains local HTTP; TLS, MFA, token expiry/live revocation, per-device
scope, rate limiting, immutable external audit archives, dependency locking and fleet
load/soak are deferred hardening. Anonymous viewer access defaults on for compatibility;
disable it for private reads. The shared legacy token cannot distinguish people.
Host owners can modify databases; SQLite eviction does not securely erase backups/pages.
Operation history remains indefinite and concurrency bounds assume one backend process.
APK validation is structural, not malware scanning or a certificate allowlist.

Recovery/bootloader reboots remain unsupported until vendor support is verified.
Sleep/lock follows Android timeout/keyguard policy and cannot guarantee secure locking.
Accepted ADB execution does not prove visual effects; cancellation/timeouts cannot
undo effects already applied on Android. Conservative package protection can reject
benign OEM apps. Rooted/other OEM hardware is unverified.

Recommended M5: verified scoped screen/input interaction, authenticated bounded streaming,
backpressure/cancellation, per-device permissions, OEM capabilities and broader hardware
acceptance. Complete the pending M4 runtime/browser checks first. Arbitrary terminal,
logcat and file-transfer contracts require separate review.

## M4.5 follow-up — 2026-10-09

M4.5 reran all regression checks and fixed a route-word device-ID authentication bypass.
Protected fleet API reads now require credentials by default; optional anonymous reads
require explicit opt-in. Browser credentials/cache/previews expire safely. Final M4.5
counts are 379 backend tests and 45 frontend tests, all checks passing. The 351/41
counts above record the earlier M4 run, not deployed acceptance.

Runtime acceptance remains BLOCKED after a fresh access retry: Docker Unix socket and
loopback binding return `Operation not permitted`, Chromium cannot start and GitHub SSH
DNS resolution fails. No active database backup, deployment, Samsung operation or runtime
persistence success is claimed. Monitoring endpoints retain a separate unauthenticated
local/trusted-network boundary. See [M4.5 validation](M4_5_VALIDATION.md) for exact checks,
security fixes, safe backup/acceptance utilities and remaining prerequisites.
