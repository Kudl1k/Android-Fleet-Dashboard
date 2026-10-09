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
history refresh is bounded to at most once a minute. Missing/stale/offline metrics
show unavailable. Chart ranges are 15 minutes, 1 hour, 6 hours, 24 hours and 7 days.

Control access accepts the existing backend bearer token into memory only. Reload
clears it. Only theme preference is stored locally. Pairing remains operator-managed;
never enter pairing codes or ADB keys into this dashboard. Same-origin proxying
avoids permissive CORS. Read APIs remain unauthenticated on this loopback deployment.

Tests use mocked API responses, not production telemetry. Browser acceptance and
actual hardware evidence are recorded separately in [M3 validation](../docs/M3_VALIDATION.md).
