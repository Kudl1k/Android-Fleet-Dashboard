# M4 frontend validation — 2026-10-09

Frontend ESLint, TypeScript checking and the production build pass. **41 tests pass
in nine files**, including all 27 M3 tests. M4 tests cover viewer/operator control
permissions, administrator reboot confirmation, offline controls, filtered package
lists, force-stop confirmation, audit/operation request suppression without read
permission, authenticated screenshot fetches with denied-image handling, cancellation
ownership, Operations/Audit filters and pagination, and audit errors.

Device details now include Device Control, installed package search and actions,
APK upload/pending state, persistent confirmed operation results and protected
screenshot previews/downloads. Fleet operations and administrator audit pages have
filters, pagination, sanitized result details and safe-operation cancellation.
Existing management and alert mutation controls use server-provided permissions.
Credential storage remains memory-only. Screenshot fetching forwards the memory
credential; the image is displayed through a local blob URL. Production Nginx CSP
includes `img-src 'self' data: blob:`. New tables have bounded horizontal scrolling
and mobile navigation wraps. These are implementation checks, not visual acceptance.

## Browser acceptance unavailable

The existing Playwright installation at `/private/tmp/adb-m3-browser/node_modules`
and its installed Chromium were discovered. A browser launch was attempted in the
current managed filesystem/process sandbox. Chromium aborted before any page opened:

```
bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer: Permission denied (1100)
```

The launch returned `Target page, context or browser has been closed` and SIGTRAP.
No browser desktop/mobile inspection, screenshot rendering under CSP, JavaScript
page-error check or visual overflow check could run. No sandbox changes or external
approval requests were made. No browser acceptance is claimed for M4. Component
and API tests use fake responses and do not establish live backend/device acceptance.

Repeat desktop dark and 390px mobile light acceptance in an environment permitting
Chromium launch: inspect permission states, explicit sensitive-action confirmation,
operations/audit pagination and filtering, protected screenshot blob preview/download,
keyboard dialog focus, document overflow and JavaScript page errors. Safe Samsung
acceptance must use actual protected backend operations separately; no real-device
actions were performed by the frontend agent.
