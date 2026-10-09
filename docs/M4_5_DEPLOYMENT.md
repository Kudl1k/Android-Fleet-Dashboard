# M4.5 deployment and preservation evidence — 2026-10-09

Deployment remains **BLOCKED** by access to the existing Docker socket. No containers
were changed, no migration was executed, no persistent volume was deleted, and no
ADB credentials were copied or displayed.

## Executed preflight

| Check / command | Result | Evidence |
| --- | --- | --- |
| `docker context ls` | PASS | Existing selected context is `colima`, socket `/Users/homelab/.colima/default/docker.sock`; contexts were not changed. |
| `docker-compose ps`, `docker --context colima ps` | BLOCKED | Permission denied connecting to that socket. |
| `docker --context colima-edit ps` | BLOCKED | `/Users/homelab/.colima/edit/docker.sock` does not exist. |
| `docker --context default ps` | BLOCKED | `/var/run/docker.sock` does not exist. |
| `colima status` | FAIL | Reports `colima is not running`; this does not establish daemon state when socket access is denied. Colima was not restarted. |
| `DOCKER_BUILDKIT=0 COMPOSE_BAKE=false docker-compose build android-manager frontend` | BLOCKED | Same Docker socket permission denial; no successful image builds. |
| Database backup / active volume inspection | BLOCKED | Container filesystem cannot be accessed without Docker socket access. |
| Restart, migration, persistence, ADB reconnect acceptance | NOT RUN | Requires active database backup and runtime access first. |

The Compose declaration preserves `adb-keys:/home/fleet/.android` and
`device-registry:/var/lib/android-fleet`, backend user UID 10001, and loopback ports
8088, 9000, 1900, 9090. This is configuration inspection, not confirmation of actual
running mounts. Active database paths, registered identifiers and record counts
cannot be reported until inspected in the running container.

## Consistent backup utility

`scripts/backup_databases.py` uses SQLite's backup API, including committed WAL
records, and verifies every copied database using `PRAGMA integrity_check`. It
creates an unpredictable timestamped directory with mode 0700 and databases and a
manifest with mode 0600. It reports table counts, registry IDs and presence of ADB
key files, never credential contents. It does not remove any database or backup.
Each database has a consistent individual snapshot; the collection is not a single
cross-database transaction. Stop externally initiated mutations during backup and
record that telemetry collection may continue.

After Docker access is restored, inspect mounts, then run before container changes:

```bash
docker-compose exec -T android-manager python - < scripts/backup_databases.py
```

Keep the manifest private: registered device identifiers are operational data.
Require exit code zero and `integrity: ok` for every expected database. Never treat
partial backup output as successful. The backup defaults to the deployment's
`/var/lib/android-fleet` directory; supply `--data-dir` if inspection shows otherwise.
To execute offline, use `python scripts/backup_databases.py --data-dir PATH --keys-dir PATH`.

Automated isolated-fixture verification **PASS**: three tests cover live WAL,
private permissions, unique destinations, credential-content exclusion, registry
counts, missing/symlink databases and corrupt databases. Command:
`.venv/bin/pytest backend/tests/test_backup_databases.py -q` → `3 passed`.
Ruff lint passes for the utility and tests.

## Coordinated acceptance once access is restored

1. Inspect project mounts and record baseline counts using the verified backup manifest.
2. Build only `android-manager` and `frontend`; run `docker-compose up -d android-manager frontend`.
3. Verify `/health`, `/ready`, authenticated APIs, frontend, Prometheus target and Grafana.
4. Exercise Samsung only through `state`, `properties`, `apps.list`, `screenshot` operations;
   poll persisted results and verify audit records and protected image download.
5. Preserve screenshot privacy; verify only PNG structure and unauthorized denial.
6. Record persistent counts, restart only the backend, compare preserved records and
   ADB key presence, then verify paired-device reconnection. Do not replay mutations.

No real Samsung or restart evidence is supplied by this document. Hardware actions,
backup execution and container changes remain coordinated by the lead agent.
