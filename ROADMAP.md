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

Implementation, automated validation and approved safe deployment/browser/Samsung
acceptance complete on 2026-10-09; see the M4.5 runtime continuation for evidence.
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
- [x] Docker image builds and deployment/restart acceptance in an authorized runtime.
- [x] Desktop/mobile Chromium acceptance.
- [x] Safe Samsung hardware state/properties/apps/screenshot acceptance.

Recovery/bootloader modes deliberately report unsupported without verified vendor
capability. Screen sleep cannot promise immediate secure keyguard locking. No actual
hardware reboot/package mutation was performed. Approved safe runtime criteria passed;
destructive hardware and broader OEM/rooted acceptance remain outside this scope.

## M4.5 – Deployment, Security Hardening & Acceptance

**Ready to close** on 2026-10-09: runtime access restored; verified active backups,
local deployment, role/audit/persistence, four safe Samsung checks, screenshot expiry,
desktop/mobile Chromium and restart/recreation acceptance passed. GitHub DNS/HTTPS
works; no publication was attempted. See [M4.5 validation](docs/M4_5_VALIDATION.md).

- [x] Fix route-word device identifier authorization bypass; regression tests.
- [x] Default protected fleet API reads to authentication; explicit anonymous opt-in.
- [x] Expire rejected browser credentials and revoke stale response/preview state.
- [x] Consistent private SQLite backup utility with integrity/count/identifier tests.
- [x] Safe four-operation REST acceptance utility with protected PNG/audit verification.
- [x] Fresh automated validation: 379 backend tests, 45 frontend tests, all lint/type/build
  checks and Compose configuration pass.
- [x] Inspect and back up active databases/volumes; verify existing ADB key persistence.
- [x] Build/deploy backend/frontend and verify health, monitoring and controlled restart.
- [x] Deployed role acceptance, Samsung properties/apps/state/screenshot and retention.
- [x] Actual desktop/mobile browser acceptance.

Only project application containers were replaced; volumes and Colima settings were
preserved. Temporary acceptance credentials/retention were restored. The
existing monitoring endpoints remain unauthenticated within the loopback/trusted-Docker
network boundary; M4.5 does not claim all telemetry surfaces require credentials.
M5 may begin within the existing local boundary; scoped permissions, bounded streaming
and private HTTPS design remain required before remote interaction deployment.

## M5 – Live Screen Mirroring & Interactive Control

Implemented and deployed within the local-only boundary. Actual Samsung SM-A356B
H.264 frames were decoded in Chromium; view-only authorization, session cleanup and
monitoring continuity passed. Automated backend/frontend, Docker and browser evidence,
measured performance and pending interactive-hardware acceptance are recorded in
[M5 validation](docs/M5_VALIDATION.md). No physical input was sent. Other OEM/rooted
devices and long-duration fleet soak remain unverified.

- [x] Version-pinned official scrcpy server via authenticated ADB and WebCodecs playback.
- [x] Owner-bound sessions/tickets, explicit `screen:*` permissions, audit and scoped RBAC.
- [x] Bounded device/user/session limits, exclusive controller, input validation/rate limit,
  reconnect, idle/disconnect recovery, cleanup and low-cardinality metrics.
- [x] Responsive view-only and explicit control UI, focused keyboard, pointer/touch,
  Android navigation, quality, fullscreen and decoder/backpressure handling.
- [x] Backend/frontend tests, static checks, image build, local deployment, browser and
  safe real-device view-only acceptance.
- [ ] Interactive input acceptance on the physical Samsung; awaiting explicit approval.

Remote TLS/identity lifecycle and shared encoder fan-out remain hardening work.
Terminal, arbitrary shell, logcat streams and file transfer need distinct contracts.

## M6 – Stability, Compatibility & Performance

Implemented and validated within the short local acceptance scope on 2026-10-10:
471 backend tests, 67 frontend tests, static checks/builds, actual Chromium/Firefox/
WebKit desktop/mobile-emulation playback, restart cleanup and a completed five-minute
view-only smoke. Stabilizes M5 through strict live geometry,
decoder lifecycle, independent viewer/device cleanup, capacity/drop metrics, browser
acceptance and a configurable no-input soak harness. Physical input and rotation remain
pending at the user’s explicit request; the user also skipped long soak completion.
The interrupted two-viewer run cleaned all owned resources. Full long-duration
certification is pending. Results and limitations are recorded in
[M6 validation](docs/M6_VALIDATION.md) and [performance](docs/M6_PERFORMANCE.md).

Advanced vendor hardware monitoring remains future scope: Qualcomm, Tensor, Exynos and
MediaTek extensions; GPU, NPU/DSP where available and evidence-based throttling detection.

## M7 – SSH & Remote Terminal Management

Implemented browser xterm terminals for registered-device ADB and approved SSH profiles,
encrypted credentials and pinned host keys, owner-bound authenticated WebSockets,
bounded session lifecycle/history/audit, and administrator Wireless Debugging pairing,
separate connect/verify/register and identity-preserving port updates. Validation and
pending acceptance are recorded in [M7 validation](docs/M7_VALIDATION.md); configuration
is in [SSH and pairing guide](docs/M7_SSH_CONFIGURATION.md). Physical shells/new pairing
and deployment remain pending explicit approval; no public SSH/ADB ports are added.

## M8 – Remote deployment hardening and fleet reliability

Private HTTPS/WSS, identity/token lifecycle, managed secret-file integration, profile
policy administration, approved hardware terminal/pairing acceptance, longer stability
runs and broader OEM coverage. Keep incremental security gates before remote release.

## School assignment – root-aware monitoring (2026-10-13)

Implemented and validated in fake mode on an Ubuntu 24.04 VirtualBox VM (Docker, Linux,
Python 3.13): 554 backend tests passed; 3 pre-existing timing-sensitive streaming/terminal
tests fail intermittently on the unmodified code too; ruff and mypy clean.
See [school assignment](docs/SCHOOL_ASSIGNMENT.md), [NAVOD.md](NAVOD.md) (Czech) and
[metrics](docs/METRICS.md).

- [x] `android_device_info` (manufacturer, model, Android, SoC with board fallback, kernel).
- [x] Root elevation through `su -c` with unprivileged fallback for ZRAM, GPU, processes,
  thermal sysfs and `/proc/stat`.
- [x] ZRAM, CPU frequency ceilings/capping, Adreno and Mali GPU backends, process count
  and bounded top-5 process CPU/memory.
- [x] Grafana fleet status table, temperature and capping; device detail panels for the above.
- [x] `device-setup/`: Magisk boot script (ADB TCP + iptables restricted to the server),
  ADB key authorization and silent su policy for the ADB shell.
- [x] Small-VM Compose override and image shipping script (~160 MiB RAM measured).
- [x] Battery charge, full/design capacity and cycle count (sysfs files unverified on lab hardware).
- [x] Read-only replay of real Pixel 3a XL root-shell outputs through all collectors
  (2026-10-13); fixed `/data_mirror` storage and zygote process names.
- [ ] ADB-transport acceptance on real rooted Pixel 3a XL / Pixel 9 Pro / Nexus 5X
  (Mali paths unverified).
- [ ] Deployment to the school VM after approval.
