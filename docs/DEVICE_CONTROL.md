# Secure device control

Device Detail includes asynchronous controls, installed-package search, metadata,
launch/force-stop, APK upload and protected screenshot preview/download. Operations
shows fleet history, filtering, results and safe cancellation. Audit is administrator
only. The UI asks for explicit reboot/uninstall confirmation and force-stop confirmation;
server-side destructive confirmation requires literal JSON `true`.

| Actions | Permission | Behavior |
| --- | --- | --- |
| `state` | `control.inspect` | Current fleet-observed connection state; available offline |
| `properties` | `control.inspect` | Approved getprop values only |
| `apps.list`, `apps.inspect` | `control.inspect` | Package names; bounded version/install metadata |
| `apps.launch` | `apps.launch` | Launcher activity through bounded monkey invocation |
| `apps.stop` | `apps.stop` | ADB force-stop; UI confirmation |
| `screen.wake`, `screen.lock` | `control.screen` | Wake/sleep key events; lock depends on Android keyguard policy |
| `screenshot` | `control.screen` | Bounded PNG from exec-out screencap |
| `apps.install` | `apps.install` | Validated uploaded APK; no `-g` permission grants |
| `apps.uninstall` | `apps.uninstall` | Confirmed non-system, non-protected package removal |
| `reboot` | `control.reboot` | Confirmed normal reboot |
| `reboot.recovery`, `reboot.bootloader` | `control.reboot_special` | Always unsupported until vendor capability verification exists |

All baseline controls use ordinary authenticated ADB on non-rooted Android. This
implementation does not bypass Android restrictions or expose `su`, arbitrary
shell, remote paths, arbitrary input, file transfer, terminal or logcat. A completed
operation means the ADB command was accepted and passed bounded result checks;
it does not prove a visual UI effect, immediate keyguard locking or reboot completion.

Approved properties: `ro.product.manufacturer`, `ro.product.model`,
`ro.build.version.release`, `ro.build.version.sdk`, `ro.product.cpu.abi`,
`ro.boot.bootloader`. The optional `property` request field selects one; otherwise
all are retrieved. Properties return a map, application listing `{packages:[...]}`,
metadata `{package,metadata:[...]}`, screenshot `{screenshot_url,bytes}`. Screenshot
URLs require authorization and never resolve through a public static directory.

## Bounds and recovery

Operations persist in `operations.sqlite3` beside the registry, using the existing
private volume. Global concurrency defaults to four; a single operation runs per
device. Queue capacity defaults to 100 outstanding operations. Devices are checked
when execution starts, and disconnect/unsupported/Android rejection becomes a sanitized
failure. Execution defaults to 30 seconds; `ANDROID_FLEET_OPERATIONS_TIMEOUTS` accepts
JSON per-action overrides, e.g. `{"apps.install":120}`. Values must be finite, positive
and at most 300 seconds. Text stdout/stderr are each limited to 1 MiB.

Queued/running jobs found after restart become failed with an interruption outcome;
no action is replayed. Graceful shutdown stops local tasks and drains ADB children.
Operation history persists indefinitely. Operators may cancel their own cancellable
inspection/screen operations, administrators any cancellable operation. Package
changes, application launch/stop and reboots cannot be cancelled through the API.
Cancellation and timeouts cannot reverse already applied device effects.

Screenshots default to 16 MiB maximum and one-hour retention. Private artifact files
are cleaned at startup, every minute and before download. Captures are PNG-signature
checked and served with `no-store` and `nosniff`. A user who downloaded an image can
retain that copy; server expiry does not revoke it.

## APK and package safeguards

Raw APK uploads require the APK media type, have a default 64 MiB streaming limit,
a 120-second upload deadline and two concurrent upload slots. Filenames supplied by
clients are never server paths. Private generated temporary files are removed after
success/failure and on restart/shutdown. APK archives are never extracted. Validation
rejects unsafe archive paths, duplicate members, excessive entry counts/uncompressed
sizes, oversized manifests and invalid binary XML chunk structure. Android Package
Manager remains responsible for full manifest semantics and signing validity;
this is not malware scanning or a certificate trust policy.

Package identifiers use an anchored ASCII segment allowlist and cannot contain shell
metacharacters, whitespace, options or paths. Uninstall checks Android's system-package
list and protects `android`, `android.*`, `com.android.*`, `com.google.android.*` and
`com.samsung.android.*`; this conservative policy can reject benign vendor packages.
Neither uninstall nor administrator roles bypass validation. Installation does not
silently grant runtime permissions, root access or allow downgrade/replacement flags.

## Acceptance and M5

Fake ADB and real bounded subprocess tests cover controls, denial paths, uploads,
serialization/concurrency, deadlines, cancellation, restart and protected screenshots.
M4 hardware acceptance is pending due session access restrictions; no destructive
hardware action was attempted. See [validation](M4_VALIDATION.md).

M5 should add verified OEM capabilities and narrowly scoped screen/input interaction,
with authenticated streaming, frame/output limits, backpressure, cancellation and
per-device authorization. Prefer those interfaces before any terminal or arbitrary
command feature. Include actual non-root Samsung and broader OEM acceptance, load/soak
validation and private-read/TLS deployment hardening.
