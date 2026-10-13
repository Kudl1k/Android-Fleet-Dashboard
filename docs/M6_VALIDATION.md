# M6 stability, compatibility and performance validation

Date: 2026-10-10. Existing M5 working-tree changes were preserved. No commits or pushes.
Scope is the existing local Docker deployment on macOS/Colima: frontend 8088, backend
9000, Grafana 1900, Prometheus 9090. Hardware is one non-rooted Samsung SM-A356B,
Android 16, Wireless ADB. No rooted/OEM fleet or physical multi-device certification.

The user explicitly chose **keep hardware input pending**. No physical touch, keyboard,
navigation or rotation change was made. A concrete reversible acceptance plan is in
[M6 input acceptance](M6_INPUT_ACCEPTANCE.md). No APK was installed or removed.

| Check | Status | Evidence |
| --- | --- | --- |
| Backend regression | PASS | 471 passed in 16.52 s, including real ADB blank-line inspection regression; includes geometry, authorization, bounded queues, controller cleanup, TCP multi-device isolation, reconnect and soak harness fixtures. |
| Frontend regression | PASS | 67 tests across 11 files; lint/type/build passed. Decoder config races, backlog reset, cleanup, rotation gesture cancellation/current coordinates, quick restart cleanup, suspended tab, unsupported browser/profile and fullscreen fixtures. |
| Ruff/format/mypy | PASS | 88 files formatted; strict typing passes 58 source/script files. |
| Compose and image build | PASS | Standalone docker-compose config and backend/frontend builds; no published port/volume/network changes. |
| Backup and persistence | PASS | SQLite backup API verified integrity `ok` for six SQLite files including historical backup; active five device IDs retained, alert/metrics/operations/audit databases preserved. External copy retained privately in /tmp/m6-runtime/database-backups. ADB key and public key remain present. |
| Scoped deployment | PASS | Only manager/frontend recreated. Existing Prometheus/Grafana stayed running. Readiness, frontend health, five devices, fresh Samsung metrics and eight alert rules verified. |
| Multi-viewer isolation | PASS (short scope) | Independent bounded viewer queues/exclusive control fixtures; actual two captures/viewers for ~137 s wall time before user cancellation, no errors/drops; all resources cleaned. Sustained 15/60-minute acceptance NOT RUN. |
| Multi-device isolation | PASS | Real loopback scrcpy video/control sockets for two simulated transports; isolated routing, rejected cross-device input, one reconnect does not disturb second, cancellation/forwards/process/task cleanup. Physical multi-device NOT RUN. |
| Geometry/rotation | PASS | Synthetic SPS portrait↔landscape, crop, resize, high profiles/scaling lists/separate planes, malformed/truncated configs. Exact live dimensions required; new-dimension cancel releases browser pointer capture. Physical rotation NOT RUN. |
| Browser decoding | PASS | Three engines × desktop/mobile emulation × three qualities passed; final-source desktop rerun and runtime matrix in [browser compatibility](M6_BROWSER_COMPATIBILITY.md). Feature probing alone is not accepted as decoding proof. |
| Performance | PASS | Actual counters and resource observations in [performance](M6_PERFORMANCE.md). Static display rates are not configured FPS guarantees. |
| Short smoke / long soak | PASS / NOT RUN | Configurable no-input 15/60/custom-minute live/simulated harness, independent heartbeats, bounded samples/resources, reconnect events, structured output and post-cleanup sampling. Completed 300.557 s single-viewer smoke; two-viewer long run interrupted by user after 137.258 s wall time. No 15/60-minute completion claim. |
| Network interruption/backpressure | PASS | Fixture transport failure, slow WebSocket send deadline, bounded per-viewer queue/keyframe recovery, slow browser decode reset, reconnect control revocation. Host network configuration unchanged. |
| Backend restart recovery | PASS | Actual view-only WebSocket closed on manager-only restart; ready returned, session list empty, zero forwarding/manifest entries, fresh Samsung metrics and eight alert rules. |
| Observability | PASS | Aggregate active viewers, accurate actual video drop accounting and capacity rejection counters; streaming Grafana dashboard startup/throughput/failures/cleanup. No private content/session/user labels. |
| Hardware interactive control | BLOCKED | User explicitly withheld approval; safe plan available. Full fixture authorization/input/ownership coverage completed. |
| Physical rotation | NOT RUN | No approval; no rotation settings changed. |
| Physical multiple devices | NOT RUN | Only one physical Android available. |
| 15-/60-minute soak completion | NOT RUN | User explicitly requested skipping the remaining long soak. Both live long run and simulated 15-minute run were cleanly interrupted; no pass inferred. |

Runtime evidence contains counters and measurements, not images, user input or bearer
credentials. Private authentication artifacts remain outside the repository and are
removed after acceptance. Long-duration browser/GPU memory and end-to-end latency
require additional instrumentation; unavailable observations are not fabricated zeros.

## Findings and resolved failures

The audit found swapped stale geometry accepted by the server, asynchronous decoder
config/closed-decoder races, stale control-acquisition responses after reconnect,
held gesture continuation after rotation, misleading stale FPS HUD and quick stop/start
capacity races. Each received a targeted correction/fixture. Initial runtime quality
restart attempts failed while cleanup still reserved capacity; serialized cleanup
corrects the behavior without relaxing resource limits. A browser probe launched during
frontend replacement received expected connection refusal; acceptance reruns follow
readiness. Neither preliminary run is reported as a successful final acceptance.

Separate device-side captures remain bounded to two viewers per device by default.
Shared capture would change quality selection, lifecycle and controller ownership;
that rewrite was excluded from this stability milestone. Measurements establish the
supported workload limits, not arbitrary fleet scaling. See [architecture](M5_ARCHITECTURE.md)
and [operations](M6_OPERATIONS.md).

## Final runtime scope

The full original M6 acceptance remains limited by intentionally pending hardware input/
physical rotation and skipped long-duration testing. Software implementation/regressions,
three-engine playback, bounded synthetic multi-device reliability and short live sessions
passed. This record does not claim full 60-minute stability certification.

Completed live single-viewer smoke: **300.557 s**, 721 framed binary packets,
234,622 bytes, first encoded packet at 2.248 s, zero stream/reconnection errors, 23 quiet
intervals and successful session cleanup. This is encoded transport, not browser FPS.

Started full live two-viewer stability run with medium 720-edge/30 FPS/3 Mbit targets,
10-second resources and 300-second planned reconnect interval. User requested skipping
it before the first scheduled reconnect: **137.258 s wall time from launch**, including
baseline sampling. At sampled times two sessions/viewers/tunnels were active, no
controllers, errors, cleanup failures, drops or capacity rejections. After interruption,
all sessions/controllers/tunnels/manifest entries were zero; fresh telemetry, registry,
alerts and monitoring remained healthy. [Structured interrupted result](m6-results/soak-interrupted.json).
The interrupted simulated run is not reported as a completed 15-minute test.

Restart/interrupt cleanup does not measure true orphan Android process counts; that
field remains unavailable. No physical device disconnect or rotation was induced.
Scheduled live soak reconnects did not execute before cancellation; reconnect evidence
comes from browser disconnect/restart, actual backend restart and TCP/fixture tests.

Deployment preserves published ports, both persistent application/key volumes and the
existing administrator credential (compared privately), five registrations and eight
rules. Deployed bridge/geometry/manager/ADB module hashes match source. Grafana's nine
streaming panels loaded and Prometheus's manager target reports up. Only project
manager/frontend containers were recreated/restarted; monitoring containers stayed up.

Next recommended milestone: M7 private HTTPS/identity lifecycle hardening, with a
scheduled full stability run and approved isolated hardware input/rotation acceptance
before claiming remote production readiness. Shared capture deserves a separate design
only if measured workload demand exceeds the supported two-viewer bound.
