# Web dashboard

React 19, TypeScript and Vite provide the M3 dashboard. TanStack Query handles
independent cached polling, React Router handles navigation, Recharts renders
history, and Lucide supplies icons. Device details use source-owned shadcn/ui (Radix Nova)
components, themed through the existing slate-and-blue tokens. Other routes migrate
incrementally. Tailwind v4 utilities run without Preflight to preserve the existing shell.

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

Use the Overview, History and Device tools tabs to switch tasks. History starts loading on first selection and retains its range. Device tools contains Live screen, Terminal, Device controls, and Setup & connectivity. Setup remains optional; monitoring uses authenticated ADB. All tool and terminal-tab content stays mounted while hidden. The workspace tab shows screen status and the open terminal-tab count; tool summaries also expose session context. Use Stop stream or Close session to finish. Route changes, authentication changes and browser-tab visibility retain the existing cleanup policies.

On Node 25, run tests with `NODE_OPTIONS=--no-experimental-webstorage npm test` to avoid the runtime's experimental web-storage conflict with jsdom.

## Extending the UI

`components.json` configures shadcn's Radix Nova registry and `@/` alias. Add only
needed components with `npx shadcn@latest add <component>`. Use individual imports
from `src/components/ui`; shared recipes and semantic token aliases live in
`src/ui.css`, while `src/styles.css` owns shell and feature layout. Do not add a
second theme, a global reset, a font download or parallel native-control wrappers.
Inspect generated changes: preserve the local `cn()` import, 44px control targets,
existing palette and no-Preflight setup. The generated Table intentionally leaves
overflow to ListRegion. ScrollArea exposes viewport props/ref for named keyboard
regions and measurement.

[DESIGN.md](../DESIGN.md) documents component composition, field validation,
confirmation focus, session lifecycle and legacy CSS compatibility. Component APIs:
[Tabs](https://ui.shadcn.com/docs/components/radix/tabs),
[Collapsible](https://ui.shadcn.com/docs/components/radix/collapsible),
[Scroll Area](https://ui.shadcn.com/docs/components/radix/scroll-area),
[Alert Dialog](https://ui.shadcn.com/docs/components/radix/alert-dialog).
