# Registry publication 2026-10-19

Built backend and frontend from clean commit `92bb99b` for `linux/arm64`.
Published both `92bb99b-20261019` and `latest` tags to the mac.lab registry
through its existing trusted alias `192.168.123.238:5000`.

Use the image values in `registry-images.env` in the Komodo stack environment.
Both tags were verified through the registry API: manifest SHA256 matched the
registry digest header, and config blobs confirmed Linux ARM64.

Backend digest: `sha256:2652ec608adc18cce71a581d836b6dffd8d5c0b99e3869b9b5009c5555bab378`.
Frontend digest: `sha256:9b931faa5849460be346503658e2fa936328b4f3446594b1beb1db75c43a89db`.

Validation: both Docker builds passed, frontend TypeScript/Vite compilation passed,
and the built backend application imported successfully. Full test/lint/type suites
were not run for this publication. Hostname API verification returned HTTP 404;
verification through the trusted IP succeeded. No daemon settings or running stack
were changed. Save the new environment values and deploy the stack in Komodo.

## Terminal button fix

Published and deployed frontend tag `92bb99b-20261019-terminal-fix` and `latest`.
Digest: `sha256:874b2b73a76f4fd5145ddccb6c2f93c83d10f77566c9fbe8998c0f1c517f19eb`.
Includes uncommitted changes replacing the browser secure-context-only
`crypto.randomUUID()` tab identifier with a component-owned counter, allowing
terminal buttons to work on plain HTTP LAN origins. A regression test exercises
two tabs with the crypto API unavailable. Terminal tests, lint and TypeScript/Vite
build passed. Only the frontend container was recreated for this fix.

The live backend also has interactive ADB enabled and terminal origins configured
for mac.lab, 192.168.123.238, localhost and 127.0.0.1 on port 8999. Preserve these
settings in Komodo's saved configuration. The temporary Colima host route for
192.168.123.105 via 192.168.64.1 on col0 is needed for device connectivity and
does not survive a VM restart.

## ADB TCP switch feature

Published both services under `92bb99b-20261019-tcp-switch` and `latest` via
`localhost:5000`, the same local registry, then deployed both existing Komodo services.
Includes the uncommitted feature changes and previous terminal HTTP fix.
Verified manifest SHA256 and Linux ARM64 config blobs through 192.168.123.238:5000.
Current digests are in `registry-images.env`. Backend health and the served action
bundle passed checks; the Samsung remained online at 192.168.123.105:5555.

Administrators can use **Switch to ADB TCP → Enable TCP and reconnect** on an online
Wireless Debugging device in its detail page or Device management. The operation
preserves registry identity and requires a verified Android serial before and after
the transport change. It rejects duplicate TCP registrations before changing mode.

Validation: 566 backend tests, 86 frontend tests, Ruff lint/format, strict backend
mypy, frontend ESLint and TypeScript/Vite production build passed. Backend tests
use fake transports, including unsupported mode, unauthorized transport, timeout,
identity mismatch, cancellation and duplicate registration cases. No fresh physical
device conversion was performed during validation because the connected Samsung
was already using ADB TCP. No commits or Git pushes were made.

## TCP restart probe recovery

Backend tag `92bb99b-20261019-tcp-probe-fix` and `latest` published and deployed.
Digest: `sha256:50d8fcacbe8df64e44cdd7b02ae30cd582d19e3412ac1d87473b71ed15126645`.
The device had switched successfully, but its subsequent shell capability probe
briefly failed and recovered on a scheduled poll. The switch now waits for up to
three capability probes within a 15-second readiness budget, and never reports
success while the device remains in probe_failed. A persistent failure explicitly
states that TCP is enabled and suggests Reconnect. Regression tests reproduce
identity verification succeeding followed by transient or persistent probe failures.
568 backend tests, Ruff lint/format, strict mypy and the backend image build passed.

## Optional F-Droid, Termux and managed SSH setup

Both images published under `92bb99b-20261019-termux-setup` and `latest`.
Current digests are in `registry-images.env`. The feature installs missing apps
from fixed official F-Droid URLs with pinned size and SHA256 validation, then
configures public-key-only Termux SSH through its foreground terminal. Managed
private keys are encrypted and reused on retries. The SSH host key is anchored
to an authenticated ADB forward before a real key-authenticated LAN login enables
the device-linked SSH profile. Setup runs through the existing bounded, audited
per-device operation queue and never replaces fleet ADB monitoring.

Validation: backend full suite (586 tests at that point), the completed setup
suite (20 tests including two additional local SSH/API integration tests), all
91 frontend tests, Ruff lint/format, strict mypy, ESLint, TypeScript/Vite and both
ARM64 image builds passed. Official APK HEAD requests returned 200 with expected
size for F-Droid 1.23.2 and Termux 0.118.3. Physical-device installation was not
started; the administrator starts it from the device page.

A new SSH encryption key was generated for the live stack (which previously had
no encryption key and zero profiles), persisted privately in its existing .env,
and passed through Compose. No key material was printed or committed. Before
changing this key, preserve the existing .env and use the documented encryption
rotation workflow if encrypted profiles exist. Private configuration backups
remain beside the live stack files. Preserve the SSH encryption environment
mapping in Komodo's saved Compose configuration.

Use **Install F-Droid, Termux & SSH**, confirm, and keep Termux foregrounded on an
unlocked primary-user Android device. Initial Android prompts may need approval.
Use **Enable Termux SSH** to retry configuration without installing again. Root,
a helper APK, broad storage permissions and Termux external-app access are not
required. Startup after reboot is not configured.

## Samsung Termux readiness fix

Backend `92bb99b-20261019-termux-focus-fix` and `latest` published and deployed.
Digest: `sha256:70bcdf4dc0eff5aa9c9f52635020ce96a117ea06912036cd36e585143921e9d1`.
Samsung's `dumpsys window windows` omitted current-focus fields despite an active
Termux shell. Setup now checks `dumpsys window displays`, with a full-window-dump
fallback, and still requires an actual primary-user focused window. Merely having
a Termux activity in the window list does not authorize input. All 596 backend
tests, Ruff lint/format, strict mypy and the backend image build passed.
