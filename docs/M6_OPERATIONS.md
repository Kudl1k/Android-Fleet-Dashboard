# Streaming stability operations

Start a view-only session first. Control requires a separate explicit request; backend
or browser reconnect never restores it. Hidden tabs stop playback and release the
session; return to the tab and restart view-only. Supported playback requires a secure
context, WebCodecs and support for the actual device H.264 SPS profile. A successful
feature probe alone is insufficient. See [browser acceptance](M6_BROWSER_COMPATIBILITY.md).

Quality presets specify the longest encoded edge: low 480/15 FPS, medium 720/30 FPS,
high 1080/30 FPS. They are ceilings; static Android displays produce fewer frames.
Geometry follows SPS on the server and decoded display dimensions in the browser.
Malformed configuration makes pointer geometry unknown and input fails closed. A
rotation cancels a held gesture; stale coordinates are rejected. Stop/restart waits for
old session cleanup before reserving capacity again.

Each viewer currently owns one encoder/tunnel and an independent bounded queue.
Default limits are two viewers per device, two sessions per identity and four globally.
Capacity errors must be resolved by stopping unused sessions or lowering demand; avoid
increasing limits without device encoder and resource measurements. Shared capture is
future bounded work with explicit quality and controller ownership contracts.

A slow viewer drops queued video until a keyframe; codec configuration is retained.
An excessively slow browser reports a lower-quality restart message. WebSocket send
has a five-second deadline. No buffering or decoder backlog should be unbounded.
A quiet display is healthy when session/readiness checks pass; five seconds without
encoded output is not by itself a stream failure.

Run the no-input soak from the repository virtual environment (development dependencies
include httpx):

```bash
.venv/bin/python scripts/m6_soak.py --mode simulated --minutes 15 --viewers 2 \
  --reconnect-seconds 300 --output /tmp/m6-simulated.json
# Supply AFM_TOKEN privately in the environment; do not put it in command arguments.
.venv/bin/python scripts/m6_soak.py --mode live --device REGISTERED_ID --minutes 15 \
  --quality medium --viewers 2 --sample-seconds 10 --reconnect-seconds 300 \
  --container adb-dashboard-android-manager-1 --output /tmp/m6-live.json
# Use --minutes 60 for full stability acceptance; longer durations are optional.
# --backend-pid samples a host-visible backend process. Container PIDs are not host PIDs.
```

The harness receives framed packets and sends tickets/heartbeats only. It never
acquires control or sends device input. Results exclude pictures, tokens and text.
Simulated success validates the harness only, not Android, browser decoding or fleet
hardware. API termination checks do not alone prove device process/tunnel cleanup.
Use --container for read-only Docker CPU/container memory, backend RSS/descriptors,
ADB forwarding and transport manifest counts, including baseline/post-cleanup checks.
Cleanup fails if new forwards remain even after an incorrectly erased manifest.
Shared background workloads make resource ownership comparison unavailable; isolate
the acceptance workload. True orphan device process counts remain unavailable.

The Grafana **Android Fleet Streaming** dashboard shows active streams/viewers/
controllers, mean transport startup, WebSocket bytes/sec, real video drops, stream and
cleanup failures and capacity rejections. Counters omit device/session/user labels.
Startup measures transport readiness; browser first decoded frame is measured separately.

Before deploying, run scripts/backup_databases.py inside the active manager, verify its
integrity manifest and preserve an external copy. Build and recreate only this project's
backend/frontend with `docker-compose up -d --no-deps android-manager frontend`.
Preserve all ports, named volumes, keys and registrations. Do not prune volumes or
change Colima networking. Verify `/ready`, `/frontend-health`, fresh device metrics,
alert rules, Prometheus and Grafana after deployment. Restart only the manager for
restart acceptance when no other acceptance stream depends on it.

If cleanup fails while a device is offline, the private transport manifest retains the
owned PID/tunnel record and retries after reconnect. Do not use broad process kills,
ADB forward --remove-all, or delete the manifest to hide failures. Backend restart cleans
recorded ownership without restoring sessions or controllers. Inspect cleanup counters
and eventual zero owned transports; an unreachable phone leaves device cleanup pending.

Interrupting a soak with Ctrl-C cancels consumer/heartbeat tasks and runs session
cleanup before exiting 130. The normal final JSON export is not written on interruption;
retain separately observed counters and mark the requested duration NOT RUN. Do not
turn an interrupted test into a pass. M6's interrupted run has an explicit partial
observation artifact in `docs/m6-results/soak-interrupted.json`.
