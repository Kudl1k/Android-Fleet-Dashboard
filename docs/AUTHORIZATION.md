# Authorization and audit

Every protected API checks an operation permission on the server. Role membership is configured by the backend, never supplied by a request. Unknown permissions are denied. Invalid credentials cannot fall back to anonymous access. Device control has no loopback exemption.

| Role | Permissions |
| --- | --- |
| Viewer | `device.read`, `telemetry.read`, `alerts.read`, `operations.read`, `screen:view` |
| Operator | Viewer permissions plus `control.inspect`, `control.screen`, `apps.launch`, `apps.stop`, `operations.cancel`, `screen:control`, `screen:session:terminate` |
| Administrator | Operator permissions plus `device.manage`, `alerts.manage`, `apps.install`, `apps.uninstall`, `control.reboot`, `control.reboot_special`, `audit.read`, `security.manage` |

Operation cancellation additionally checks ownership for operators. Administrator permissions do not bypass package validation, protected-package checks, explicit destructive confirmation, Android restrictions, upload validation or command allowlists.

## Provisioning

No external identity provider is required. Generate a different high-entropy bearer token for each person; do not use a password. This local example prints the token once for secure distribution and its SHA-256 digest for configuration:

```python
import hashlib
import secrets

token = secrets.token_urlsafe(32)
print("Token:", token)
print("Digest:", hashlib.sha256(token.encode()).hexdigest())
```

Set `ANDROID_FLEET_RBAC_CREDENTIALS` to a JSON array in the backend environment or a protected deployment environment file:

```text
ANDROID_FLEET_RBAC_CREDENTIALS=[{"identity":"operator-alice","role":"operator","token_hash":"REPLACE_WITH_64_LOWERCASE_HEX_DIGITS"},{"identity":"admin-bob","role":"administrator","token_hash":"REPLACE_WITH_A_DIFFERENT_64_HEX_DIGIT_DIGEST"}]
ANDROID_FLEET_ANONYMOUS_VIEWER=false
ANDROID_FLEET_AUDIT_RETENTION_SECONDS=7776000
```

The placeholder configuration is intentionally invalid until replaced. Identity must contain only letters, digits, underscore, dot, at-sign or hyphen and be at most 80 characters. Invalid roles, duplicate identities and duplicate token hashes fail startup. The identities `anonymous`, `unauthenticated` and `legacy-administrator` are reserved to prevent attribution and operation-ownership aliases. Use restrictive permissions on the configuration file. Rotate or revoke credentials by replacing/removing their configuration records and restarting the backend. Tokens are authenticated using constant-time digest comparison; raw configured RBAC tokens are not stored.

Existing `ANDROID_FLEET_CONTROL_TOKEN` remains an administrator credential with identity `legacy-administrator`. This preserves existing management clients but provides no individual attribution. Migrate to individual tokens and remove the legacy token when practical. Hashes are appropriate for random high-entropy tokens; they are not a password hashing scheme.

Send `Authorization: Bearer TOKEN`; `X-Control-Token` is accepted for compatibility. Never put tokens in URLs. `/api/v1/auth/me` returns the authenticated identity, role and exact permission list. The browser uses those permissions to present controls; backend checks remain authoritative.

`ANDROID_FLEET_ANONYMOUS_VIEWER` defaults to false: fleet reads require authentication. An explicit true setting preserves the legacy anonymous read-only dashboard workflow and exposes device, telemetry, alert and operation data to anyone who can reach the backend. Enable it only after assessing that exposure. When false, device, telemetry, alert and operation reads require valid credentials. Health and monitoring endpoints retain their deployment role; restrict monitoring access at the network boundary. A bearer token must be transported over TLS outside the local host. The existing local HTTP deployment does not provide transport encryption, MFA or an identity lifecycle service.

## Audit storage and maintenance

The backend stores audit history in `security.sqlite3` beside the registry database. The database has restrictive file permissions; preserve its directory/volume across redeployment. Entries record timestamp, actor identity and role, device, action, request/operation identifier, authorization result, execution outcome, duration and a sanitized machine error code. Tokens, pairing codes, keys, APK contents and ADB output are not audit payloads. Rejected privileged actions are recorded. Public APIs cannot update or delete audit records, and a database trigger rejects updates.

Administrators may query `GET /api/v1/audit`, with `actor`, `device_id`, `action`, `authorization`, `outcome`, `limit` (1–200) and `offset` filters. Results contain `items`, `total`, `limit`, `offset`; timestamps are Unix seconds. Operators and viewers cannot read the audit trail.

`ANDROID_FLEET_AUDIT_RETENTION_SECONDS` controls retention (90 days by default). Startup and maintenance remove expired rows; ordinary writes append records. SQLite can reuse freed pages; removal does not promise forensic erasure. Database backup and filesystem permissions remain the deployment owner's responsibility. This is an application append-only trail, not cryptographic tamper evidence: a host administrator with database or code access can alter history. There is no public audit mutation API, export forwarding or immutable external archive in M4.

## M5 screen sessions

Viewers and operators may create authenticated view-only screen sessions. Operators and administrators may acquire interactive control or terminate their own sessions. Terminating another actor's session requires administrator status. Screen sessions remain owned by their creating identity; knowing a UUID cannot grant access. Owners may stop their own sessions with `screen:view`. Administrators may terminate another actor's session through the explicit terminate endpoint, subject to device scope. Exclusive control is released on disconnect, timeout, failure, stop or restart and must be requested again explicitly.

Named credentials may include optional `device_ids`, a list of registered UUIDs. An omitted value retains fleet-wide access; an empty list permits no devices for screen actions. **This scope is enforced for M5 screen permissions only; it does not scope pre-existing monitoring or M4 operations.** Do not rely on it as a fleet-wide isolation policy. Anonymous compatibility reads do not authorize screen viewing.

Screen audit events record session start/stop, control acquisition/release and denied authorization/session access. They record neither individual keystrokes nor text, clipboard data or video. Stream tickets are random, short-lived, single-use and session-bound; existing REST authentication issues them. They are not an independent identity system. Credential configuration changes still require backend restart.

## M7 permissions

All authenticated roles receive terminal:view for their own metadata. Administrator
receives terminal:adb, terminal:ssh, terminal:profile:manage and terminal:session:terminate.
Operators have no terminal creation permission by default; named operator RBAC records
may explicitly grant terminal:adb/terminal:ssh/terminal:session:terminate through the
permissions array. Viewers cannot receive these grants. Profile ACLs do not bypass global
permission or device scope. Pairing endpoints require security.manage (administrator).
