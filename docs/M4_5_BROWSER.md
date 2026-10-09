# M4.5 frontend and browser acceptance — 2026-10-09

## Executed automated checks

PASS — `cd frontend && npm test`: 45 tests across 9 test files.

PASS — `npm run lint`, `npm run typecheck`, `npm run build` (production Vite build).

New regression tests verify expired credential invalidation, rejection of screenshots completing after a credential change, isolation of replacement credentials from earlier request failures, and preview removal/object URL revocation when credentials change. Existing component tests cover viewer/operator restrictions, administrator reboot confirmation, force-stop confirmation, offline controls, application search, history permission restrictions and audit pagination. These are automated jsdom/component checks, not browser runtime acceptance.

## Security and UX fixes

A 401 for the active in-memory credential now clears authentication and cached data. Successful responses from an earlier credential are discarded after a credential change. Screenshot requests use the same invalidation and response isolation. Device-control state resets when the identity token or selected device changes, removing previous screenshot previews and pending confirmations; object URLs are revoked on unmount. Sign-in copy now explicitly covers viewer/operator/administrator access to protected fleet data. Credentials remain in memory only.

## Browser attempts

Executed from `/private/tmp/adb-m3-browser` using the installed Playwright package:

```sh
node -e 'const {chromium}=require("playwright"); chromium.launch({headless:true}).then(async b=>{console.log("Chromium launch PASS");await b.close()}).catch(e=>{console.error(e.message);process.exit(1)})'
node -e 'const {chromium}=require("playwright"); chromium.launch({channel:"chromium",headless:true}).then(async b=>{console.log("Chromium launch PASS");await b.close()}).catch(e=>{console.error(e.message);process.exit(1)})'
```

BLOCKED — Chromium headless shell exited with SIGTRAP. Browser log: `bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.<pid>: Permission denied (1100)`.

BLOCKED — supported full Chromium channel exited with SIGABRT before a session opened. Playwright reported `Target page, context or browser has been closed`; cleanup `kill` returned EPERM.

No browser session successfully opened. No desktop/mobile screenshots were taken. No API requests, hardware actions or mock-browser acceptance were substituted for live acceptance. Sandbox approval is disabled for this environment, so permission escalation was unavailable.

## Required live scenarios

BLOCKED — desktop and mobile fleet overview, detail, Device Control, installed applications, protected screenshot capture, operation/audit histories, role-aware actions, expired-session behavior, confirmation dialogs, loading/error/offline states, console errors and failed-request inspection. Browser launch restrictions prevent all of these runtime checks; deployed localhost reachability is separately tracked in the lead validation report.

M4.5 browser acceptance remains incomplete. Run these scenarios against the deployed M4 images in an environment permitting Chromium bootstrap/IPC and localhost connections before M5.
