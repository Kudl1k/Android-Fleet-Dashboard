# M7 terminal and Wireless Debugging architecture

M7 adds an application-owned terminal gateway. The browser uses xterm.js and FitAddon; credentials stay on the backend. SSH uses AsyncSSH and ADB sessions use the existing `AdbClient` boundary. The ADB baseline requires no SSH server, management APK or root. No host Docker socket, privileged container or public ADB port is added. SSH mode connects to a separately configured standard SSH server.

## Ownership and authorization

`TerminalManager` owns session transports, cancellation tasks, bounded output queues, one-use tickets and session metadata. `terminal:view` permits the terminal UI and metadata access. Creating a session requires `terminal:adb` or `terminal:ssh`; viewers cannot create sessions. Interactive ADB is disabled until `ANDROID_FLEET_TERMINAL_ADB_ENABLED=true` is configured. ADB sessions resolve a registered device ID to its serial and verify live online state and the observed shell capability. The browser cannot supply arbitrary serials. No `su` is invoked.

SSH profiles require `terminal:profile:manage` for administration. A profile's identity ACL and optional device scope apply in addition to `terminal:ssh`. An administrator can manage profiles and terminate sessions under the existing device scope policy. Session reads, tickets, attachment and ordinary closure require ownership; administrator termination uses a separate permission and audit event naming the actual administrator.

Authorization is checked when creating and attaching, on each input and output message, and periodically during active sessions. Revoked profile access terminates sessions. No terminal input or output is stored in the database, browser storage, audit, or metrics.

## Version 1 WebSocket contract

REST `POST /api/v1/terminal/sessions` accepts `connection_type` (`adb` or `ssh`), one matching `device_id` or `profile_id`, and optional `cols`/`rows`. It returns the session metadata. `POST /api/v1/terminal/sessions/{id}/ticket` issues a ticket valid for 30 seconds, replacing an older outstanding ticket for that session.

Connect to `/api/v1/terminal/sessions/{id}/stream` with subprotocols `fleet-terminal.v1` and `ticket.<ticket>`. Authentication, session ownership, profile scope and exact allowed Origin are checked before accepting the socket. The selected subprotocol is `fleet-terminal.v1`. Tickets are single-use and never appear in URL query strings. Reverse proxies must forward WebSocket upgrades and must not log the credential subprotocol header.

All application messages are JSON text with an exact integer `version: 1`; booleans and floating point versions are rejected. Extra fields are forbidden.

| Direction | Type | Payload |
| --- | --- | --- |
| Browser to backend | `input` | `data`: UTF-8 string |
| Browser to backend | `resize` | `cols`: integer 2–500; `rows`: integer 2–200 |
| Both | `heartbeat` | No payload; server acknowledgment |
| Browser to backend | `close` | No payload |
| Backend to browser | `output` | `data`: UTF-8 text preserving ANSI/control sequences |
| Backend to browser | `status` | `state` and optional sanitized `reason` |
| Backend to browser | `error` | Sanitized `code` and `detail` before authenticated protocol/transport rejection |

Incoming messages are limited to 4096 UTF-8 bytes, matching the container Uvicorn frame limit; the data field also has a 4096-character schema ceiling. Input is limited to 100 messages and 65536 encoded bytes per second. Output reads are at most 16384 bytes and use incremental UTF-8 decoding. The default output queue holds 16 chunks. Queue insertion, socket sends and transport writes have five-second deadlines. Slow clients cause transport failure and cleanup rather than unbounded retention.

## Lifecycle and persistence

States are `connecting`, `active`, `disconnecting`, `closed`, `failed`, and `timed_out`. Global, user and associated-device limits reserve connecting and disconnecting sessions too. Defaults are 16 globally, four per user and two per device. Metadata records actor, target, timestamps, duration, state and sanitized termination reason in a separate SQLite database.

The default idle timeout is 300 seconds and maximum lifetime is 3600 seconds. Only terminal input extends the idle deadline; heartbeat traffic confirms socket health and does not keep an unused privileged shell open indefinitely. Browser disconnects, remote EOF, device disconnects, revocation, cancellation and failures close resources. Backend shutdown closes live sessions. Startup marks previously active persistent rows closed with `backend_restart`; privileged sessions are never automatically reconnected. The frontend reconnect action explicitly creates a new session.

The ADB adapter starts `adb -s <registered serial> shell -tt` through argv execution and a local raw PTY. Window-size changes use `TIOCSWINSZ` and explicitly notify the owned ADB client with `SIGWINCH`, since the subprocess has no controlling terminal/process group. ADB's stdin thread uses this signal to forward remote window changes; see the [ADB client source](https://android.googlesource.com/platform/packages/modules/adb/+/refs/tags/platform-tools-34.0.0/client/commandline.cpp). Process cancellation kills and reaps the owned subprocess. Baseline sessions retain the Android shell user's permissions. SSH allocates `xterm-256color`, resizes the channel PTY, enables connection/login timeouts and keepalives, disables implicit agent/config use, and closes its connection on failure.

## SSH trust and encrypted profiles

The default destination allowlist is empty. Each administrator-approved host and port must match the allowlist; resolution rejects prohibited address classes, and privileged service ports including Docker API and ADB server ports are prohibited. Connections dial the resolved address, avoiding a second hostname resolution during the SSH handshake.

First-use host-key retrieval is distinct from approval. The administrator confirms the SHA256 fingerprint; approval stores the public host key. Sessions require that key and enforce AsyncSSH verification. A changed host key fails until explicitly reapproved. Profiles expose a credential reference, never the stored secret. Credentials are encrypted with Fernet using a separately managed encryption key; passwords are never plaintext SQLite values. See the SSH configuration guide for key rotation, credential replacement and backup/recovery. Backups must preserve encrypted database records and separately protect the encryption key.

## Wireless Debugging wizard

Pairing and connection are separate administrator-only operations through the existing container-local ADB client. The pairing code goes through subprocess stdin, never process argv, logs, persistent storage or API responses. Pairing output is bounded and sanitized. Timeouts kill/reap the process; attempts are rate limited. Administrators manage bounded private IP/CIDR approvals in the dashboard; approvals persist in `pairing.sqlite3` and are audited. Environment values seed a new installation once and do not override dashboard changes on restart.

The wizard explains Android setup, collects the pairing address/port/code, clears the code after success or failure, then requests the distinct connection port. Successful pairing does not imply connection. Users can retry connection without re-pairing, verify model/manufacturer/version/identity, assign a name and register through the persistent inventory. Reconnect/update-port retains the existing registration and history. ADB trust persists through the existing credential volume. mDNS discovery is optional; manual entry is the supported fallback when Docker/Colima multicast is unavailable.

## Observability and deployment boundary

Session creation/rejection, termination, connection failures, profile/credential changes and host-key approval are audited with sanitized machine codes. Keystrokes, output, passwords and keys are excluded. Terminal metrics report active SSH/ADB sessions, failures, timeouts, duration and cleanup failures without user, host, profile, device or session labels.

Existing deployment ports, SQLite volumes, device registrations, ADB credential mounts and scrcpy routes are preserved. The backend container includes AsyncSSH dependencies and ADB, runs as its existing unprivileged user and supports PTYs. M7 runtime acceptance is isolated; physical Samsung shell and new pairing acceptance remain pending explicit approval. Detailed PASS/BLOCKED/NOT RUN evidence is recorded in `M7_VALIDATION.md`.
