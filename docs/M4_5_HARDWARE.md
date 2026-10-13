# M4.5 safe hardware and operation acceptance — 2026-10-09

**PASS** — actual deployed REST acceptance supersedes the historical runtime blocker.
The existing registration named `Pixel` is non-rooted Samsung **SM-A356B**; this does
not establish Google Pixel, rooted or other OEM acceptance. Backend ADB sees the
previously authenticated wireless device; RSA keys persist across container recreation.

`scripts/m4_safe_acceptance.py` was executed through its `run` function with a private,
temporary administrator token and the explicit existing registered Samsung identifier.
Only the four approved actions were submitted by the utility. Values and pixels were
not printed or published.

| Action | Result | Actual observed states / evidence |
| --- | --- | --- |
| state | PASS | `succeeded` already present at submission response; transient earlier states were not invented. |
| properties | PASS | `running` → `succeeded`; history and matching successful audit verified. |
| apps.list | PASS | `running` → `succeeded`; history and matching successful audit verified. |
| screenshot | PASS | `running` → `succeeded`; history and matching successful audit verified. PNG 1080×2340, 180,753 bytes, framing and chunk CRCs valid. |

All four actions have persisted history and successful audit records. Browser acceptance
made two additional approved screenshot captures while correcting the harness and
verifying protected preview, giving six completed operations in total. No other successful
hardware action was submitted. Unauthorized requests were rejected before execution.

Screenshot download: missing credentials 401, viewer 403, operator/administrator 200.
Responses contain `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
Actual screenshot naturally aged beyond temporary 120-second retention: HTTP 404 at
152.3 seconds, and matching PNG absent from the container artifact directory. History
and audit remained. The default 3600-second retention was restored; a full hour was
not waited out. Desktop/mobile Chromium both decoded and displayed protected preview.
No protected screenshot pixels were included in browser evidence screenshots.

Six completed operation rows and the pre-restart 67 audit rows survived backend restart
and subsequent container recreations. Final automatic recreation reconnected Samsung
in 3.1 seconds without pairing or manual ADB intervention. See
[deployment evidence](M4_5_DEPLOYMENT.md) for the earlier transient deadline failure.

Previously completed fake-client timeout/offline/cancellation/recovery tests remain
valid isolated evidence, not additional hardware acceptance. The existing offline
registration was used for browser controls; Samsung was never deliberately disrupted.
Reboot, recovery, bootloader, install/uninstall, force-stop, wake/lock, root and arbitrary
shell acceptance were NOT RUN. No APK was installed or uninstalled. Unsupported vendor
features and broader hardware remain outside this safe acceptance scope.
