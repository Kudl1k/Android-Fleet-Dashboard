# M4.5 frontend and browser acceptance — 2026-10-09

**PASS** — actual Chromium runtime acceptance supersedes the historical sandbox
launch failures. Chromium **156.0.8078.4** ran against deployed localhost M4 services,
at desktop **1440×1000** and mobile **390×844** with touch/mobile emulation for the
main mobile session. This is Chromium emulation, not physical mobile-browser testing.

The previously completed 45 tests in nine files, lint, typecheck and production build
were not unnecessarily rerun. Docker image construction reran the TypeScript/Vite build.
Existing stale credential/cache/preview regressions remain separately recorded unit
coverage. No frontend implementation change was required by this continuation.

| Scenario | Desktop / mobile result |
| --- | --- |
| Sign-in and fleet overview | PASS — real Samsung shown, five registrations; no horizontal viewport overflow. Fleet screenshots visually inspected for mobile layout. |
| Device detail and Device Control | PASS — live detail and controls rendered. |
| Installed applications search | PASS — actual previous `apps.list` result filters `com.android`; nonexistent search gives zero package rows. |
| Protected screenshot preview | PASS — actual authenticated PNG decodes to natural width 1080, preview closes. No preview pixels saved in browser screenshots. |
| Confirmation dialog | PASS — administrator opens normal reboot confirmation then cancels; Confirm action never clicked, no reboot submitted. |
| Operation/audit history | PASS — real operation and audit filters show successful screenshot entries. |
| Management/alerts navigation | PASS — deployed pages render; no browser device registration/removal or alert mutation performed. |
| Viewer restrictions | PASS — capture disabled, audit navigation absent. |
| Operator restrictions | PASS — capture enabled; reboot and APK upload disabled. |
| Offline controls | PASS — existing `pixel-offline` registration shows unavailable controls; inspect disabled and layout has no viewport overflow. |
| Loading and error states | PASS — real operation response delayed one second by pass-through browser interception exposes loading state; actual missing-device 404 renders error. No fabricated backend response. |
| Credential persistence | PASS — tokens absent from localStorage/sessionStorage; page reload clears identity. |
| Revoked active credential | PASS — remove temporary backend credentials, navigate active browser to fleet, actual HTTP 401 clears identity and privileged navigation. |
| JavaScript/network diagnostics | PASS — zero JavaScript page errors; expected 401 for unauthenticated/revoked sessions and 503 for offline telemetry. No unexpected network failures. |

Initial harness retries fixed a hidden filter-option selector and use of full navigation
(which correctly clears in-memory credentials). They were not application regressions;
only the final successful scenarios are counted as acceptance. Loading delay affects
request timing only; protected data and screenshot checks used actual deployed responses.

Local evidence is private under `/private/tmp/m45-runtime`: `browser-evidence.json`,
`browser-extra.json`, desktop/mobile fleet and offline screenshots. No tokens or
protected screenshot pixels were published or added to Git. Acceptance tokens were
revoked and the normal backend configuration restored.
