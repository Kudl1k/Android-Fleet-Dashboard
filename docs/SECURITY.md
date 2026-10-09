# Security

The backend enforces operation permissions, records persistent audit events and
executes only allowlisted device controls. Read [authorization](AUTHORIZATION.md)
for credential provisioning, role permissions and audit retention, and
[device control](DEVICE_CONTROL.md) for bounded execution and APK safeguards.
No unauthenticated loopback control exception remains. ADB trust is privileged
infrastructure and the loopback deployment is not a production security certification.

## Deployment boundary

All four published service ports remain bound to loopback. Never publish ADB server
5037 or expose Android wireless ADB ports to untrusted clients. Preserve standard
ADB RSA authentication and Wireless Debugging trust. Protect keys and database
volumes with restrictive permissions and private backups; registration removal
and transport disconnect do not revoke Android-side trust keys.

Named credentials store hashes of high-entropy random tokens, never passwords or
raw RBAC tokens. The legacy control token remains a shared administrator credential
for compatibility. Tokens stay in frontend memory and are never put in URLs or
browser storage. Anonymous viewer access defaults to disabled; fleet data requires authentication. Explicitly enabling anonymous reads is a legacy compatibility option that exposes fleet data. Use TLS and
an authenticated management network before deploying beyond localhost. Prometheus,
Grafana, health and API-schema endpoints have their existing deployment boundary;
application RBAC does not replace their network protection.

## Execution safeguards

All production subprocess work remains behind `AdbClient`. Local execution uses
argv, never `shell=True`; remote argv is quoted. Public APIs cannot select arbitrary
commands, shell text, filesystem paths or root execution. Output, screenshots,
APK uploads, upload concurrency, operation concurrency and execution time are bounded.
Android security restrictions remain authoritative. Control baseline needs no root;
existing capability probes retain their prior explicitly configured behavior.

Package arguments are validated and protected/system packages cannot be uninstalled.
APK archives are not extracted; paths, ZIP/member bounds and binary manifest chunk
structure are validated. Android Package Manager performs final signature/package
validation. No automatic permission-grant flag is passed during installation.
Screenshots have authenticated delivery, private storage, size and retention limits.
Raw ADB output, APK bytes, tokens, pairing codes and keys are not audit payloads.
Audit errors use fixed machine codes and operation errors are sanitized.

## Remaining hardening

Roles currently apply fleet-wide; per-device scope, MFA, token expiry, live revocation,
external identity integration, TLS automation, immutable external audit archives,
request rate limiting and dependency/image digest locking remain future hardening.
Host administrators can alter application code/databases despite application audit
immutability. SQLite retention does not guarantee secure erasure or shrinking files.
Operation history is retained indefinitely; capacity planning and long-duration fleet
load/soak testing remain necessary. One backend process owns jobs and the ADB lifecycle;
multiple Uvicorn workers are unsupported. Cancellation cannot undo Android-side effects.

Keep credentials out of source and logs. mDNS is observation, not identity proof;
ADB authentication remains required. Do not install agents, SSH servers or management
APKs to bypass Android restrictions. Preserve `ADB_MDNS_AUTO_CONNECT=0` and existing
Colima networking; proxy headers never grant privileges.

## Local HTTP and future remote access

Loopback HTTP is not encrypted. Keep the current local ports private. For future
remote use, place an HTTPS reverse proxy on an authenticated private network, restrict
backend and monitoring ingress to that proxy/network, and configure an explicit
origin allowlist if cross-origin browser access becomes necessary. Do not publish
ADB or enable remote access as part of this milestone. Same-origin frontend API
proxying avoids a permissive CORS policy.

## Monitoring exception

Authenticated reads are the default for protected fleet REST APIs, not every network
surface. `/metrics` and Prometheus queries expose device identifiers and telemetry
without application bearer authentication. They retain loopback-published and trusted
Docker-network access for existing scraping. Before remote access, exclude monitoring
routes/ports from general ingress or use trusted authenticated infrastructure and a
separate scrape credential design. Securing `/metrics` alone would not secure Prometheus
queries. Runtime monitoring must be verified before changing scrape credentials.
