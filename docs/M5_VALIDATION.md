# M5 implementation and validation — 2026-10-10

Implementation and local deployment are complete within the existing loopback
boundary. Real Samsung view-only video and desktop/mobile Chromium playback passed.
Physical-device input remains **pending**: this milestone explicitly withheld touch,
keyboard, navigation and every other input event on the Samsung. The accepted hardware
scope therefore does not claim interactive hardware acceptance.

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| Architecture and protocol | PASS | Official scrcpy 3.3.4 server and protocol; image build verifies upstream SHA-256. H.264 Annex B access units go straight to Chromium WebCodecs, without transcoding. See [architecture](M5_ARCHITECTURE.md). |
| Backend automated tests | PASS | 412 passed. Covers session ownership/lifecycle, scoped authorization, tickets/origin, exclusive controller, input validation/rate limits, bounded queue/keyframe recovery, idle/offline/reconnect, slow-client timeout, shutdown and recovery, ADB framing/cleanup and application integration. |
| Frontend tests | PASS | 58 passed across 11 files. Includes WebCodecs lifecycle, ticket negotiation, sizing/letterboxing, focused keyboard, pointer, permissions, quality, fullscreen, disconnect and cleanup. |
| Ruff and format | PASS | `ruff check backend`; `ruff format --check backend` (83 files). |
| Mypy | PASS | Strict check of 56 source files. |
| Frontend lint/type/build | PASS | ESLint, TypeScript, Vitest (58), production Vite build. |
| Compose configuration | PASS | `docker-compose config --quiet`; original service ports and named volumes retained. |
| Container build/deployment | PASS | Backend and frontend images built. Only those two project services were recreated; Prometheus and Grafana stayed running. `/ready` returned 200, `/frontend-health` returned `ok`. New screen module hashes inside the deployed backend matched the built source. |
| Persistence and credentials | PASS | Existing five device registrations and stored databases/key volume were backed up and integrity checked before deployment. Existing pairing credentials remained present and the Samsung reconnected. Temporary browser acceptance role hashes were removed after the test; the original role configuration and legacy administrator token were restored. |
| Direct Samsung video | PASS | Non-rooted SM-A356B, Android 16, 592×1280 H.264. A real authenticated WebSocket delivered SPS/PPS/configuration and 11 video packets during 14.65 s; first decoded transport frame arrived in 1.62 s in this run. A previous view-only run delivered 23 packets / 85,368 bytes in 11.26 s; the active-session restart test delivered 37 packets / 86,465 bytes in 35 s. Static-display packet cadence varied; this is not a 30 FPS guarantee or a controlled maximum-FPS measurement. |
| Browser desktop playback | PASS | Chromium 156.0.8078.4 decoded a non-empty canvas at 592×1280, fit without horizontal overflow; fullscreen, 720p preset, stop/restart, disconnect UX and route cleanup exercised. No user control action was made. |
| Browser mobile playback | PASS | Chromium 156.0.8078.4 at 390×844 with touch emulation decoded the same live stream and fit without horizontal overflow; lower quality, stop/restart, disconnect and route cleanup exercised. Fullscreen was not run in mobile emulation. |
| Rotation on Samsung | NOT RUN | No display rotation was triggered on the physical phone. Dimension changes and coordinate mapping have fixture coverage. |
| Browser memory observation | PASS | Desktop and mobile Chromium heap observed during a bounded session with explicit garbage collection between samples. The short sample supports cleanup testing but does not establish a long soak or fleet-scale memory ceiling. |
| Quality settings | PASS | Desktop and mobile Chromium changed from the default 1280 target to the 720 preset and decoded 336×720 output; no quality change was requested through the physical phone. |
| View-only enforcement | PASS | Deployed viewer start/list succeeds; control acquisition returns HTTP 403. Browser exposes disabled navigation/control buttons and sends only its ticket/heartbeats. No touch, key, navigation, clipboard or other input was sent to the Samsung. |
| Monitoring continuity | PASS | Fresh device telemetry remained available during streaming; existing scrape and health checks remained operational. Screen metric names are low-cardinality and omit session/user identifiers. |
| Session cleanup/restart | PASS | REST stop, browser disconnect and route change close sessions; deployed statistics returned `stopped`. With an actual Samsung view-only stream active, restarting only `android-manager` closed its WebSocket, removed the owned scrcpy tunnel, and returned ready with no live session restored. The transport manifest was empty; Samsung reconnected and current telemetry remained fresh. ADB tunnel/PID recovery and retry are covered by tests. One earlier Wi-Fi cleanup shell timed out; its bounded retry succeeded. |
| Interactive hardware acceptance | NOT RUN | No physical input was injected, pending explicit approval. Fake/fixture tests exercise control serialization, permission denial, exclusive ownership and release cleanup. |
| Firefox/Safari | NOT RUN | Runtime feature checks show an explicit unsupported error where WebCodecs/H.264 is unavailable; no compatibility claim was established for either browser. |
| Long-duration, multi-device soak | NOT RUN | Concurrency limits, packet bounds and slow-client behavior have automated coverage; a sustained multi-device resource soak was not run. |

The deployed browser test also verified view-only and operator permission states,
quality restart, reconnect after a browser socket close, error messaging when WebCodecs
is removed, and theme compatibility. Login probes emitted expected 401s before
credentials were entered; no page JavaScript errors were observed. The first browser
instrumentation attempt bound an unmodified WebCodecs static method through a test
proxy and interfered with codec negotiation; the corrected instrumentation/browser run
passed, and the independent raw Chromium WebSocket check confirmed binary frame delivery.

## Performance and resource notes

The stream avoids backend decoding and re-encoding. Android MediaCodec, browser decode,
and frame forwarding still use device/server/browser resources. Each viewer creates
its own scrcpy encoder and ADB tunnel; defaults cap the system at four active sessions,
two per user and two per device. The device-side maximum is 30 FPS and 4 Mbit/s at
1280 pixels by default, adjustable before session start.

On a static display, the desktop Chromium HUD sampled 3.7 FPS and 4 ms local decode
delay; the mobile emulation sampled 0.4 FPS and 5 ms. First decoded frames appeared
in 2.05 s desktop and 1.75 s mobile. These short rates vary with Android frame
production and the sample window. Ten post-GC desktop JS heap samples ranged from
10.99 to 13.08 MB; three mobile samples ranged from 10.96 to 10.98 MB. Browser heap
samples do not measure GPU memory or backend/device memory. No repeatable bandwidth
ceiling, peak CPU or long soak result is claimed. Local decode delay is not network
round-trip or end-to-end latency.

## Remaining scope

Interactive input is implemented behind `screen:control`, explicit control acquisition,
per-device exclusivity, short bounded schemas and rate limits, but remains unverified
against the physical Samsung pending approval. Broad OEM/rooted-device behavior is not
certified. Local HTTP remains local-only; remote use still needs a private HTTPS/VPN
boundary, identity/token lifecycle and review. M6 should measure sustained multi-viewer
CPU/bandwidth, consider shared-encoder fan-out, test rotation/input on hardware after
approval and expand OEM/browser coverage. Terminal, arbitrary shell, logcat streaming
and file transfer remain separate future contracts.
