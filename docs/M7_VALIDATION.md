# M7 terminal and Wireless Debugging validation

Date: 2026-10-11. Pre-existing M5/M6 working-tree changes preserved. Images were published
to the local registry as authorized; no commits, production deployment or physical-device
commands/pairing occurred.

Status vocabulary: PASS means executed successfully; FAIL means an executed check failed;
BLOCKED means a required check could not execute; NOT RUN means intentionally unexecuted.
Hardware and deployment acceptance remain pending, independently of software passes.

## Acceptance scope

M7 implements ADB PTY terminals behind `AdbClient`, AsyncSSH sessions through exact approved
destinations and pinned host keys, Fernet-encrypted profiles, owner-bound ticket WebSockets,
bounded lifecycle/history/audit and xterm tabs. Pairing uses code stdin, distinct connection
ports, online verification, fleet registration and identity-preserving port updates.
See [architecture](M7_ARCHITECTURE.md) and [configuration](M7_SSH_CONFIGURATION.md).

| Check | Status | Evidence |
| --- | --- | --- |
| Backend regression | PASS | **537 passed in 29.75 s**, including four real loopback SSH integration tests, PTY resize signal delivery, private-CIDR authorization and persistent administrator-managed pairing approvals. Normal CI requires no real devices. |
| Ruff lint/format and typing | PASS | Backend and scripts checked with backend CI configuration; mypy covers backend source/scripts. |
| Frontend tests, ESLint, TypeScript, production build | PASS | **81 tests across 14 files**; xterm initialization, tabs, focus/input, resize, timeout/errors, ACL/profile fingerprint confirmation, pairing navigation/retry/code clearing and in-app network approval. |
| Credential encryption and host keys | PASS | Encrypted SQLite bytes, wrong-key failure, atomic key rotation, secret-free read/error APIs; actual loopback SSH pinned-key acceptance and changed-key rejection. |
| Authorization and WebSocket protections | PASS | Auth before accept, exact Origin, one-use ticket/session ownership, viewer denial, scope and ACL revocation, malformed/oversized/version schemas, rate/queue/session limits. |
| Session resources and recovery | PASS | Real local PTY control bytes/resize/process reap and explicit owned-client SIGWINCH notification without a controlling terminal; slow-output queue failure/cleanup, browser disconnect, idle/lifetime timeout and restart metadata fixtures. Actual disposable backend restart closes its socket, preserves closed metadata and returns zero active counters without privileged replay. |
| Standard OpenSSH PTY acceptance | PASS | Disposable Alpine OpenSSH container on the private Docker network, no published SSH port. Candidate fingerprint independently checked against server public host keys; encrypted password profile, initial stty size 24×80, resize to 40×120, Ctrl+C interrupts sleep 30 and a subsequent command completes within eight seconds. Session closes and server shell resources disappear. |
| Real SSH/WebSocket integration | PASS | Disposable loopback AsyncSSH server, generated host key/test credentials, real Uvicorn WebSockets, concurrent terminals, ANSI/control bytes/resize and clean transport closure. No unrelated network hosts used. |
| Chromium desktop/mobile browser | PASS | Chromium 156.0.8078.4, desktop 1440×1000 and mobile 390×844 emulation, resize to 1100×850/844×390. Real nginx WebSocket upgrades; two fake ADB + one real SSH tabs, ANSI rendering/echo, SSH Ctrl+C, focused input, resize frames, reconnect at device capacity, tab cleanup, SSH navigation and wizard. No page JavaScript errors. Structured evidence in m7-results. |
| Pairing API | PASS | Fake pairing success/failure/code validation/timeouts, exact-IP and bounded private-CIDR allowlists, broad/public range rejection, persistent in-app approval/revocation across restart, administrator authorization/audit, rate limits, secret redaction, separate connection/verification/registration, duplicate identity, unauthorized/offline transport and wrong-device port update rejection. |
| First-time pairing wizard | PASS (fake transport) | Desktop/mobile browser pairing, separate connect/verify, friendly-name registration and navigation. No hardware handshake performed. |
| Standalone/Komodo Compose | PASS | Both configurations validate with supplied placeholder image/monitoring variables. Existing port/volume mappings remain unchanged. |
| Backend/frontend images | PASS | Administrator-managed pairing settings backend/frontend images are built and published as m7-20261011.2 and latest under mac.lab:5000/android-fleet. Registry API confirms the tags and digests recorded in deploy/komodo/M7_IMAGE_MANIFEST.json. Non-root Linux backend opens PTYs and finds ADB binary. |
| Existing stack health and data reads | PASS | Existing 9000 readiness, 8088 frontend health and 9090 Prometheus readiness; authenticated reads retain five registrations and readable alerts/audit/authentication. Existing ADB key/public key files present. No active volumes/database/schema modified by M7 runtime tests. |
| Actual Samsung terminal | NOT RUN | No approval to start physical interactive shell; container-local ADB inspection currently lists no connected transports, zero online registered devices. |
| Physical new pairing handshake | NOT RUN | Explicit approval absent. Pending physical acceptance; software/fake workflow is not a hardware success claim. |
| Actual scrcpy screen playback | NOT RUN | No connected physical transport during M7 acceptance. Existing screen API/bridge/geometry/session/integration regression suites pass; M6 evidence remains separate. |
| mDNS discovery reliability | NOT RUN | Existing adb mdns services inspection returns an empty list. Neither TLS service type was observed in Colima; manual pairing/connection is fully available. No networking changes. |
| Production migration/deployment | NOT RUN | Explicit approval absent; active database backup is required before any future migration/rollout. Runtime acceptance uses isolated disposable storage and loopback ports 18088/19090. |
| Public remote HTTPS readiness | NOT RUN | Existing local HTTP boundary preserved. Private HTTPS/WSS and identity lifecycle remain M8 scope. |

## Preliminary findings and corrections

Security review added strict protocol integer-version validation, credential/key-error
redaction, SSH mutation locking, host-key replacement audits and creation/termination
authorization metadata. Unicode/control paste frames are measured as serialized UTF-8
and preserve code points. Reconnect waits for prior termination to avoid capacity races.

The initial browser harness expected echo of individually typed characters in a single
packet; using a paste input corrected that assertion. Its first AsyncSSH test server used
line editing, which translated Ctrl+C into a signal the fixture did not handle. A raw test
PTY fixture corrected that harness mismatch. An immediate resize assertion preceded the
FitAddon/DOM update; waiting for layout yielded both desktop/mobile passes. These failed
preliminary runs are not counted as acceptance passes. A browser run started before
backend readiness failed its permission-dependent UI wait; the readiness-gated final
image rerun passed. The first OpenSSH fingerprint assertion assumed Ed25519; comparing
the negotiated candidate against the server’s trusted RSA/ECDSA/Ed25519 fingerprints
corrected the fixture without changing or relaxing gateway host-key verification.

The full suite emits a pre-existing Starlette/httpx TestClient deprecation warning;
frontend tests emit jsdom's unimplemented canvas warning from existing screen fixtures.
Neither prevents checks passing. No terminal content, real credentials or pairing codes
are included in the structured validation artifacts.

## Limits and M8

Physical terminal/new pairing acceptance remains pending approval. No Termux/OpenSSH was
installed. SSH accepts dedicated unencrypted private-key material (encrypted at rest) or
passwords; separate key passphrases/SSH agent/proxy/port forwarding are not implemented.
Without stable Android serial properties, port updates constrain the same approved IP
but cannot conclusively distinguish a different device reusing that IP. SSH DNS changes
require administrator reapproval. Encryption keys supplied through container environment
are visible to trusted Docker administrators; use a managed secret store and separately
back up the key. Local HTTP is not remote production TLS certification.

Recommended M8: private HTTPS/WSS, token/identity rotation, managed secret-file support,
profile policy administration, approved Samsung shell/pairing and broader OEM acceptance,
plus longer concurrent terminal/screen stability and resource measurements.
