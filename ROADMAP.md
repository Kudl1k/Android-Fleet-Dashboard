# Roadmap

## M0 – Foundation

Verified baseline: 40 tests, lint/format, typing and the existing Docker stack passed inspection on 2026-10-09.
Repository conventions, AGENTS.md, architecture/security/development docs, Python project, Docker Compose, read-only FastAPI skeleton, fake ADB, initial real ADB adapter, bounded probing, battery/RAM parsers and Prometheus vertical slice, CI test/lint/type setup. Exit requires successful checks; environmental blockers must be reported.

## M1 – Device connectivity

Software implemented and automated/Docker validation passed on 2026-10-09. Hardware acceptance remains pending; do not mark real-device connectivity or multicast pairing as verified. See [M1 validation](docs/M1_VALIDATION.md).

- [x] SQLite configuration registry, UUIDs, uniqueness and versioned initialization.
- [x] Guarded CRUD/connect/disconnect/capability refresh and discovery API.
- [x] Bounded ADB connect/disconnect, reconciliation, jitter/backoff and intentional disconnect persistence.
- [x] Optional exact-identity mDNS port refresh and manual IP/port fallback.
- [x] Root/non-root capability probing, fake mode and stale metric cleanup.
- [x] Tests, lint/format, typing, Compose config/build and isolated runtime/restart checks.
- [ ] Actual Pixel authorization, TCP/TLS pairing, reconnect and multicast acceptance on the target network.
Persistent configuration registry, ADB TCP lifecycle, Wireless Debugging pairing and mDNS discovery, reconnect/backoff, stable identities, state transitions, capability evidence and refresh, rooted/non-rooted probing refinements.

## M2 – Core monitoring

Completed and validated on 2026-10-09: 261 tests, lint/format, typing, Compose build/config and real non-rooted SM-A356B monitoring/restart acceptance. The registration named Pixel is Samsung hardware; actual Google Pixel acceptance remains unverified.
Implemented: battery, interval CPU/per-core frequency, RAM/swap, `/data` storage, network counters, uptime, live thermal observations; normalized partial snapshots, freshness and bounded per-device scheduling independent of connectivity. Separate bounded SQLite history and current/history APIs preserve registry data. Fleet/device Grafana dashboards are included as requested M2 deliverables. Validation and actual hardware coverage are recorded in [M2 validation](docs/M2_VALIDATION.md); broader OEM/rooted hardware support remains unverified.

## M3 – Web Dashboard & Alerting

Implemented React/TypeScript fleet overview, device detail and historical charts,
authenticated device management, dark/light responsive navigation, and server-owned
SQLite alert rules/events with sustained conditions, hysteresis, per-device overrides,
acknowledgement, automatic recovery and paginated history. Production nginx frontend
uses same-origin API routing at localhost:8088; existing backend/monitoring ports and
persistent volumes are preserved. See [M3 validation](docs/M3_VALIDATION.md) for final
automated, Docker, real-device and browser evidence and remaining limitations.

## M4 – Secure Remote Device Control

Implementation and local automated validation complete on 2026-10-09; deployment,
browser and real-device acceptance remain pending due session sandbox restrictions.
See [M4 validation](docs/M4_VALIDATION.md) for exact results and limitations.

- [x] Fleet-wide viewer/operator/administrator operation permissions, named hashed tokens,
  legacy administrator compatibility and removal of unauthenticated loopback controls.
- [x] Persistent application append-only audit, denial/outcome records, filters and retention.
- [x] Persistent bounded jobs, per-device serialization, deadlines, safe cancellation and
  interrupted-job recovery without replay.
- [x] State/properties, application listing/metadata/launch/stop/install/confirmed removal,
  confirmed normal reboot and protected expiring screenshots.
- [x] APK/package validation, private temporary files, subprocess/output limits and tests.
- [x] Permission-aware Device Control, Operations and Audit UI, explicit confirmations.
- [x] Resolved alert retention and evaluation health metrics/reconnect regression tests.
- [x] Backend/frontend tests, lint, typechecking, production frontend build and Compose config.
- [ ] Docker image builds and deployment/restart acceptance in an authorized runtime.
- [ ] Desktop/mobile browser acceptance (Chromium launch denied by sandbox).
- [ ] Safe Samsung hardware state/properties/apps/screenshot acceptance (runtime inaccessible).

Recovery/bootloader modes deliberately report unsupported without verified vendor
capability. Screen sleep cannot promise immediate secure keyguard locking. No actual
hardware reboot/package mutation was performed. M4 must not be marked fully accepted
until pending runtime/hardware criteria pass.

## M4.5 – Deployment, Security Hardening & Acceptance

**Incomplete** on 2026-10-09: Docker/localhost IPC, browser startup and GitHub SSH
remain blocked in this execution session, including after the access-change retry.
See [M4.5 validation](docs/M4_5_VALIDATION.md) for PASS/BLOCKED/NOT RUN evidence.

- [x] Fix route-word device identifier authorization bypass; regression tests.
- [x] Default protected fleet API reads to authentication; explicit anonymous opt-in.
- [x] Expire rejected browser credentials and revoke stale response/preview state.
- [x] Consistent private SQLite backup utility with integrity/count/identifier tests.
- [x] Safe four-operation REST acceptance utility with protected PNG/audit verification.
- [x] Fresh automated validation: 379 backend tests, 45 frontend tests, all lint/type/build
  checks and Compose configuration pass.
- [ ] Inspect and back up active databases/volumes; verify existing ADB key persistence.
- [ ] Build/deploy backend/frontend and verify health, monitoring and controlled restart.
- [ ] Deployed role acceptance, Samsung properties/apps/state/screenshot and retention.
- [ ] Actual desktop/mobile browser acceptance.

No active volumes, credentials, containers or Colima settings were modified. The
existing monitoring endpoints remain unauthenticated within the loopback/trusted-Docker
network boundary; M4.5 does not claim all telemetry surfaces require credentials.
Finish blocked runtime acceptance before starting M5 implementation.

## M5 – Scoped Remote Interaction

Build on M4 permissions/jobs for narrowly scoped screen/input interaction with
protected streaming, bounded frames/output, backpressure, cancellation and per-device
scope. Verify OEM-specific capabilities and broader non-root hardware support. Finish
M4 runtime/mobile acceptance, TLS/private-read deployment hardening and load/soak tests.
Terminal, arbitrary shell, logcat streams and filesystem transfers require distinct
security contracts and remain deferred; they are not automatically enabled by M4.

## M6 – Advanced hardware monitoring
Qualcomm, Tensor, Exynos and MediaTek extensions; GPU, NPU/DSP where possible; thermal throttling detection with evidence and graceful fallback.

## M7 – Hardening
Authentication, authorization, audit log, TLS/reverse proxy, production deployment, observability, key lifecycle and long-term stability. Security work is incremental and gates earlier control functionality, not postponed until after public release.
