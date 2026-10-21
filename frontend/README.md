# Web dashboard

React 19, TypeScript and Vite provide the M3 dashboard. TanStack Query handles
independent cached polling, React Router handles navigation, Recharts renders
history, and Lucide supplies icons. Shared CSS design tokens and native form/dialog
controls keep the application small without a second component framework.

Requires Node 22+ and a running backend at http://127.0.0.1:9000.

```bash
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to the backend; use its printed local URL. For production see
[Docker deployment](../docs/DOCKER.md): http://127.0.0.1:8088.

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

`src/features/fleet` owns overview/detail/charts, `features/alerts` owns rules and
incident history, and `features/management` owns registration and connection
controls. `src/lib` contains the typed HTTP client, query hooks, memory-only control
authentication and toast notifications. Polling is selectable in the app header;
device history follows that interval after its first opening. Missing/stale/offline metrics
remain unavailable. Chart ranges are 15 minutes, 1 hour, 6 hours, 24 hours and 7 days.

Control access accepts the existing backend bearer token into memory only. Reload
clears it. Only theme preference is stored locally. Pairing remains operator-managed;
never enter pairing codes or ADB keys into this dashboard. Same-origin proxying
avoids permissive CORS. Protected read APIs require authentication by default; anonymous compatibility reads are an explicit backend opt-in.

Tests use mocked API responses, not production telemetry. Browser acceptance and
actual hardware evidence are recorded separately in [M3 validation](../docs/M3_VALIDATION.md).

## Live Screen (M5)

Open an online device's detail page and choose **Start view-only**. Current Chromium with WebCodecs on localhost or HTTPS is the primary target. Unsupported decoder/profile combinations show an error instead of screenshot polling. Choose Wi-Fi, Balanced or Detail quality before starting; quality changes require stop/start. Fullscreen and fit sizing preserve aspect ratio. Displayed FPS measures decoded frames; local decode delay is not end-to-end latency.

Control never activates automatically. An operator or administrator with `screen:control` must choose **Request control**; only one session can control a device. Click/focus the canvas to send keyboard input. The focus indicator shows when keys are active; page-global keys are not captured. Pointer down/move/up supports taps, long presses, swipes and drags with mouse or primary touch. Navigation buttons provide Back, Home, Recent apps, Wake and volume. Text/IME compatibility depends on Android; audio, clipboard synchronization and multi-touch are not implemented.

Release control or stop when finished. Route changes, sign-out and browser disconnect clean up the session. Temporary transport recovery releases control; request it again after recovery. A failed or disconnected socket requires a fresh view-only start. Slow decoding produces a lower-quality restart message. Backend ownership and input checks remain authoritative even when buttons are disabled.

Unit tests use fixtures and mocked transport; they do not prove hardware playback. See [M5 validation](../docs/M5_VALIDATION.md) for actual Chromium, Samsung and pending interactive acceptance.

## Interface guidance

See [design direction](../DESIGN.md) and the [UI review and validation](../docs/UI_REVIEW.md) for shared tokens, responsive behavior, accessibility conventions, and verification limits.

## Device workspace

Device details prioritize connection status, one collection/freshness area, and up to four available key observations. Expand Performance, Memory & storage, Battery & thermal, or Network to inspect details; Metric availability lists sources missing from the latest collection. Network observations remain cumulative counters, not rates. Missing, stale, disconnected, loading and failed collections are distinct states; failed connection checks also withhold cached current values.

Use the History link or Historical telemetry disclosure for the existing ranges and recorded-run charts. History starts loading when first opened and retains the selected range after collapse. Device tools contains Live screen, Terminal, Device controls, and Setup & connectivity. Setup remains optional; monitoring uses authenticated ADB. Live screen and terminal remain mounted when collapsed. Stream status is visible in the live-screen summary; use Stop stream or Close session to finish. Route changes and authentication changes retain the existing tool cleanup behavior.

On Node 25, run tests with `NODE_OPTIONS=--no-experimental-webstorage npm test` to avoid the runtime's experimental web-storage conflict with jsdom.
