# Registry publishing validation — 2026-10-10

No Git commit or push, Komodo deployment, production-container removal, daemon configuration change or Colima networking change was performed.

| Check | Status | Evidence |
|---|---|---|
| Existing Compose configuration | PASS | `DOCKER_CONTEXT=colima docker-compose config --quiet` |
| Context / architecture | PASS | context colima; daemon aarch64; images linux/arm64 |
| Registry HTTP API and resolution | PASS | macOS HTTP /v2/ 200; Colima and Periphery resolve mac.lab to 192.168.123.238 |
| Registry HTTPS | FAIL | TLS handshake fails; registry serves HTTP |
| Direct mac.lab Docker pushes/pulls | FAIL | HTTP response to HTTPS client; hostname absent from insecure registry list |
| Hostname-native deployment | BLOCKED | User requested daemon remain unchanged |
| Backend Dockerfile build | PASS | ARM64 build completed, cached layers reused; installed dependencies, fleet non-root user |
| Frontend Dockerfile build | PASS | ARM64 production build completed, cached npm/build layers; unprivileged nginx |
| Version and latest publication | PASS | Both repositories/tags pushed via already-trusted 192.168.123.238:5000 alias |
| Registry manifests and digests | PASS | All four retrieved via mac.lab HTTP with OCI Accept header; SHA256 of manifest bytes matches Docker-Content-Digest |
| Architecture / config blob | PASS | Config blobs retrieved from registry: linux/arm64 |
| Digest image pulls | PASS | Both digest references pulled successfully through trusted IP |
| SQLite backup and integrity | PASS | SQLite backup API, integrity_check inside container and on macOS copied backups; six files including historical device DB |
| ADB trust backup | PASS | Private copy of .android, including adbkey and adb_known_hosts.pb; no key contents printed |
| Persistent storage / networks | PASS | Four existing external volumes inspected; existing absolute monitoring binds verified in Colima; lab-network unnecessary |
| Komodo Compose configuration | PASS | Config validation using example env plus non-secret temporary Grafana password |
| Monitoring health commands | PASS | Existing Prometheus readiness and Grafana health endpoints accessible using specified wget commands |
| Isolated backend readiness | PASS | Temporary fake-ADB container, private container-layer DB paths; /ready 200 |
| Isolated frontend and proxy | PASS | Container-network /frontend-health and / return 200; /api/v1/devices rejects anonymous access with 401 |
| Python dependencies / scrcpy | PASS | pip check succeeds; bundled server checksum matches pinned scrcpy 3.3.4 hash |
| Initial smoke attempts | FAIL | Initial backend used unwritable default /app/data; localhost frontend probe failed; an unversioned /api/devices probe returned 404. Corrected explicit paths, IPv4/container DNS and /api/v1/devices checks passed |
| Cleanup helper lint / format / typing | PASS | ruff check, ruff format --check, mypy; CLI help checked without mutation |
| Git whitespace validation | PASS | git diff --check |
| Full application unit suite | NOT RUN | Application source unchanged by this deployment task; existing dirty work retained |
| Real-device reconnect and streaming | NOT RUN | No hardware session started or interrupted |
| Komodo deployment / persistence after cutover | NOT RUN | Deployment explicitly excluded from authorization |
| Production cleanup | BLOCKED | Awaiting confirmation of exact four targets and downtime |
| Consistent Grafana / Prometheus full-volume archives | NOT RUN | Original volumes preserved; stopped archive procedure provided for approved cutover |

## Snapshot baseline and storage

Backup: container `/var/lib/android-fleet/backups/komodo-20261010T180229Z`; macOS `/Users/homelab/Development/adb-dashboard/backups/komodo-20261010T180229Z` (ignored by Git). Baseline: 5 devices, 319478 samples, 8 rules, 29 alert events, 6 operations, 409 audit records. Exact table counts and backup file hashes remain in private `inventory.json`. Individual SQLite backups are consistent; they are not a single multi-database point-in-time transaction. Data continues growing in the running stack.

Preserved volumes: `adb-dashboard_device-registry`, `adb-dashboard_adb-keys`, `adb-dashboard_prometheus-data`, `adb-dashboard_grafana-data`. Monitoring bind sources stay in `/Users/homelab/Development/adb-dashboard/monitoring`. No migration, empty replacement volumes or volume deletion.

## Publication limits

Images contain the pre-existing dirty working tree at Git HEAD `2ba42d3affcab3241667236789c901d323f4f18a`; commit alone cannot reproduce them. Immutable digest references are in [IMAGE_MANIFEST.md](../deploy/komodo/IMAGE_MANIFEST.md). The registry stores the published content under the required android-fleet repositories and serves it through mac.lab, but Docker cannot use that hostname until HTTP trust is addressed. The guide provides verified IP digest overrides without daemon changes. Registry HTTP is suitable only for the trusted lab network. Loopback Compose bindings are preserved; external LAN isolation through Colima forwarding was not independently tested.

The isolated smoke containers and their temporary network are removed after checks; they never mounted production volumes. All four original project containers remain running.
