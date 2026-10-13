# M4.5 deployment and preservation evidence — 2026-10-09

**PASS** — runtime continuation 19:55–20:03 UTC supersedes the previous sandbox
blockers. Docker server 29.5.2, running Colima and all localhost services are reachable.
GitHub DNS and HTTPS succeed. No SSH login, commit or publication attempted.

## Backup before deployment

Actual manager mounts are `adb-dashboard_adb-keys:/home/fleet/.android` and
`adb-dashboard_device-registry:/var/lib/android-fleet`. Both RSA key files exist;
contents were never displayed. `scripts/backup_databases.py` ran in the active manager
before any replacement. Every copied database passed `PRAGMA integrity_check`.

Private backup directory:
`/var/lib/android-fleet/backups/20261009T195558Z-fe9c2bce55f14964861de424fe124265`.
A second copy at `/private/tmp/m45-runtime/predeployment-backup` was independently
integrity-checked on the host. Directory permissions are 0700, original snapshots and
manifest 0600. SQLite backup includes committed WAL. These are individually consistent
snapshots; ongoing collection means there is no cross-database atomic snapshot.

| Active database | Before deployment | Final verified backup |
| --- | --- | --- |
| devices.sqlite3 | 5 registrations | 5 registrations |
| alerts.sqlite3 | 8 rules, 4 events | 8 rules, 5 events |
| metrics.sqlite3 | 64,753 samples | 66,262 samples |
| operations.sqlite3 | Absent | 6 completed operations |
| security.sqlite3 | Absent | 145 audit rows |

The historical `devices.pre-m2-20261009T141428Z.sqlite3` snapshot was also backed up
and integrity-checked; it is not the active registry. Final backup:
`/var/lib/android-fleet/backups/20261009T200324Z-7edf538b8cb247aa866ea7907f0b302a`,
also copied to `/private/tmp/m45-runtime/final-backup`. All six snapshots pass integrity.

## Build and deployment

Executed `docker-compose build android-manager frontend` successfully. Compose warns
that buildx is absent, then builds successfully using the classic builder. Backend image
`6d190cf6bae6`; frontend `f8257650f63a`. Frontend TypeScript/Vite production build passes.
Application code was unchanged; dependencies remain unlocked as already documented.

Only these two services were recreated with `up -d --no-deps`. A private temporary
Compose override appended three acceptance role hashes while preserving existing
credentials, and set screenshot retention to 120 seconds. `.env` remained unchanged.
After acceptance, normal `docker-compose up -d --no-deps android-manager` restored
existing credentials and 3600-second retention. All temporary tokens now return 401.

Final backend `/health`, `/ready`, frontend `/frontend-health`, Prometheus `/-/ready`
and Grafana `/api/health` return 200. Both application containers are healthy. All four
ports retain loopback binding: 8088, 9000, 1900, 9090; 5037 is not published.

## Persistence and recovery

Backup-to-live SQL comparisons found zero missing original registration configuration,
rule rows, stable event fields or telemetry rows. Reconnect timestamps and event
state/body change through normal monitoring. Counts alone were not used as proof.

Before restart, a second verified backup recorded six completed operations and 67 audit
rows. `docker-compose restart android-manager` restored readiness and Samsung online;
all those operation/audit rows survived unchanged. Final comparisons again found zero
missing rows; audit increased through browser sign-in/denial/revocation acceptance.

One recreation while restoring normal settings remained offline after a 30-second
wait. Diagnostic `SubprocessAdbClient.connect` succeeded with existing RSA trust.
To distinguish manual recovery from automatic acceptance, a final clean
`docker-compose up -d --no-deps --force-recreate android-manager` was executed and
observed exclusively through HTTP: Samsung online and `/ready` 200 after 3.1 seconds,
without manual ADB intervention or new pairing. The transient deadline failure is retained.

Prometheus target `android-manager:8000` is up with empty `lastError`; query `up` = 1.
Grafana 11.6.0 health is OK; authenticated Prometheus datasource health HTTP 200:
“Successfully queried the Prometheus API.” Monitoring containers kept their earlier
creation times and were not recreated/restarted. No volume deletion, Colima changes,
unrelated Docker-stack changes, public exposure or destructive hardware actions occurred.
