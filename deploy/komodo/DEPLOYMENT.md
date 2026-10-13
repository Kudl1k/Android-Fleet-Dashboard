# Komodo deployment on Colima

Prepared 2026-10-10. No Komodo deployment or old-stack removal has been performed.

## Registry and current blocker

Registry HTTP API: `http://mac.lab:5000`; HTTPS fails. Both version and latest tags were published through its existing trusted alias `192.168.123.238:5000` and verified through `mac.lab`. Docker context is `colima`, daemon architecture `aarch64` (images `linux/arm64`). The daemon trusts the IP and localhost, but **does not trust mac.lab:5000**. Hostname pulls/pushes fail with HTTP response to HTTPS client. User chose to leave daemon unchanged. No Colima networking changes or unrelated restarts were made.

The supplied Compose defaults to the requested mac.lab references. For deployment without daemon changes, set these environment overrides to the same verified registry content:

```dotenv
BACKEND_IMAGE=192.168.123.238:5000/android-fleet/backend@sha256:f96f8665ca686db4f1a89ee350601f0ad1114d4da075da1746eb5795ca7aef46
FRONTEND_IMAGE=192.168.123.238:5000/android-fleet/frontend@sha256:5ac714b30cc89002342818c2da0380f30c9bac0b058c6a7ef1afc1db5bff8c5c
```

If mac.lab references are mandatory, deployment remains blocked until a separately approved daemon configuration change and maintenance restart. Add that exact hostname to insecure registries while retaining existing entries; do not restart Colima automatically. HTTP registry traffic is unencrypted: keep it on the trusted lab network.

```sh
cd /Users/homelab/Development/adb-dashboard
curl -fsS http://mac.lab:5000/v2/
for service in backend frontend; do
  for tag in 2ba42d3 latest; do
    curl -fsS -D - -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' "http://mac.lab:5000/v2/android-fleet/$service/manifests/$tag"
  done
done
docker --context colima pull 192.168.123.238:5000/android-fleet/backend@sha256:f96f8665ca686db4f1a89ee350601f0ad1114d4da075da1746eb5795ca7aef46
docker --context colima pull 192.168.123.238:5000/android-fleet/frontend@sha256:5ac714b30cc89002342818c2da0380f30c9bac0b058c6a7ef1afc1db5bff8c5c
```

## Persistent storage inventory

Exact container IDs, project labels, bind paths and daemon paths are in `deployment-inventory.json`. All four volumes are external; missing volumes cause deployment failure instead of silently creating empty data.

| Existing volume / bind source | Container destination | Permissions | Secrets / backup |
|---|---|---|---|
| `adb-dashboard_device-registry` | `/var/lib/android-fleet` | UID/GID 10001; private subdirectories 0700 | Device registrations, telemetry, alerts, operations, audit, control artifacts and screen state; SQLite online backup plus stopped archive for other files |
| `adb-dashboard_adb-keys` | `/home/fleet/.android` | UID/GID 10001; adbkey 0600; known hosts 0640 | Private RSA key and pairing trust; private archive/copy |
| `adb-dashboard_prometheus-data` | `/prometheus` | UID/GID 65534; preserve ownership | Historical telemetry; stopped archive or supported TSDB snapshot |
| `adb-dashboard_grafana-data` | `/var/lib/grafana` | UID 472, GID 0; preserve ownership | Grafana database/configuration can contain secrets; stopped archive or SQLite backup |
| `/Users/homelab/Development/adb-dashboard/monitoring/prometheus/prometheus.yml` | `/etc/prometheus/prometheus.yml` | Readable by UID 65534; read-only mount | Configuration; copy/version backup |
| `/Users/homelab/Development/adb-dashboard/monitoring/grafana/provisioning` | `/etc/grafana/provisioning` | Readable by UID 472; read-only | Datasource/dashboard configuration; copy/version backup |
| `/Users/homelab/Development/adb-dashboard/monitoring/grafana/dashboards` | `/var/lib/grafana/dashboards` | Readable by UID 472; read-only | Dashboard JSON including streaming; copy/version backup |

Daemon volume sources are `/var/lib/docker/volumes/<exact-volume-name>/_data` **inside Colima**, not macOS. Do not mount these internal paths manually; reuse Docker volumes. No migration is needed. Never deploy a second writer against the old stack's volumes.

Backend databases: `devices.sqlite3`, `metrics.sqlite3`, `alerts.sqlite3`, `operations.sqlite3`, and `security.sqlite3` (audit, derived beside registry). Online SQLite backup using SQLite's backup API was created at `/var/lib/android-fleet/backups/komodo-20261010T180229Z` and copied to macOS `backups/komodo-20261010T180229Z`. Every backup passed `PRAGMA integrity_check` both inside the container and after copying. ADB trust was copied without displaying key contents. Backups contain secrets; keep them private and outside Git. These are consistent individual database snapshots, not a simultaneous transaction across databases.

Recorded snapshot counts: 5 devices, 319478 telemetry samples, 8 alert rules, 29 alert events, 6 control operations, 409 audit entries. Exact table counts and SHA256 checksums are in the private backup `inventory.json`. Live telemetry/audit counts will continue growing. Grafana/Prometheus data remains in the existing volumes; no live raw archive is claimed to be consistent.

For full-volume backups after confirmed downtime and before deployment, first verify all four old containers are stopped/removed, then run:

```sh
cd /Users/homelab/Development/adb-dashboard
mkdir -p backups/komodo-cutover
chmod 700 backups/komodo-cutover
for volume in adb-dashboard_device-registry adb-dashboard_adb-keys adb-dashboard_prometheus-data adb-dashboard_grafana-data; do
  docker --context colima volume inspect "$volume" >/dev/null || exit 1
  docker --context colima run --rm --user 0 --mount "type=volume,src=$volume,dst=/source,readonly" --entrypoint tar mac.lab:5000/android-fleet/backend:2ba42d3 -C /source -czf - . > "backups/komodo-cutover/$volume.tar.gz" || exit 1
  chmod 600 "backups/komodo-cutover/$volume.tar.gz"
  tar -tzf "backups/komodo-cutover/$volume.tar.gz" >/dev/null || exit 1
done
shasum -a 256 backups/komodo-cutover/*.tar.gz
```

Restore only during downtime after backing up current state, preserving owners, and to the exact original volume. Do not replace or clear live volumes automatically.

## Komodo setup and initial deployment

1. Open `http://mac.lab:9120` and authenticate. Open Servers and select the existing server whose Periphery is `komodo-periphery-1`, controlling the Colima daemon. The UI server display name cannot be determined from Docker alone; verify it lists the four `adb-dashboard` containers.
2. Create Stack `android-fleet`. Set Server to that existing server and Compose project name to `android-fleet`.
3. Choose **Write in the UI / File Contents**. Paste `deploy/komodo/compose.yaml` as `compose.yaml`. Set run directory `/etc/komodo/stacks/android-fleet`, file paths `compose.yaml`. Disable automatic updates; use digest references.
4. Paste `.env.example` entries into Stack Environment and supply private secrets there. Use the trusted-IP image overrides above unless hostname trust has separately been fixed. Set `MONITORING_ROOT=/Users/homelab/Development/adb-dashboard/monitoring`.
5. Preserve the current private `ANDROID_FLEET_CONTROL_TOKEN` from local `.env` securely. Current backend has a control token and no RBAC credentials; keeping this preserves existing authorization. If configuring named users, use JSON credentials with SHA256 token hashes and roles as described in `docs/AUTHORIZATION.md`; keep client tokens private. Do not enable anonymous viewer access. Preserve the existing Grafana password; existing Grafana DB already stores its administrator account, so changing the bootstrap variable alone does not rotate it.
6. Keep real ADB enabled (`FAKE_ADB=false`, `SEED_FAKE_DEVICES=false`), `ADB_SERVER_HOST` empty and `ADB_MDNS_AUTO_CONNECT=0`. The backend owns its local ADB server; port 5037 is not published. Database paths are fixed inside Compose. Streaming uses the bundled checksum-verified scrcpy 3.3.4 server. Origin allowlist is JSON and should contain only trusted frontend origins. Default `localhost` and `127.0.0.1` origins preserve local access.
7. Do not click Deploy until exact old-container cleanup is confirmed and performed. Same ports and volumes cannot be used concurrently. Take the stopped full-volume backup above at cutover.
8. Click Save, then Deploy in the Stack. Inspect the deployment command output, Containers health and each service's logs. Expected ports remain loopback 8088, 9000, 1900, 9090.

Periphery runs in Docker and cannot read the macOS repository through its own namespace. Its `/etc/komodo` is a bind from the Colima VM's `/etc/komodo` to the same container path: UI-written stack files work there. Docker bind sources are evaluated by the daemon, not Periphery. The repository monitoring path was checked inside Colima and is already used by the running containers; absolute paths intentionally avoid relative stack-directory mounts. Keep that repository path available. The VM path `/etc/komodo/stacks/android-fleet` is not macOS `/etc/komodo/stacks/android-fleet`.

The stack needs no communication with the other lab-network services. It uses its own Compose bridge; do not attach it to `lab-network`.

Optional pre-deployment validation in Periphery after UI saves files/environment:

```sh
docker --context colima exec komodo-periphery-1 sh -c 'cd /etc/komodo/stacks/android-fleet && docker compose --env-file .env -f compose.yaml config --quiet'
```

Komodo supplies its configured environment file; if its path differs from `.env`, use the path shown in deployment logs. Supported configuration methods and fields are documented in [Komodo Compose documentation](https://komo.do/docs/deploy/compose).

## Safe old-stack cleanup — confirmation required

All targets have `com.docker.compose.project=adb-dashboard`, working directory `/Users/homelab/Development/adb-dashboard`, config file that directory's `docker-compose.yml`:

| ID prefix | Name | Service |
|---|---|---|
| `cb3f62f2395a` | `adb-dashboard-android-manager-1` | android-manager |
| `467ed107b8e9` | `adb-dashboard-frontend-1` | frontend |
| `8030b4ee5aae` | `adb-dashboard-prometheus-1` | prometheus |
| `0ca8c5ae0144` | `adb-dashboard-grafana-1` | grafana |

Removing these running containers causes dashboard/API, ADB sessions, screen streaming, scraping and Grafana downtime until Komodo deploys. No removal has been authorized yet. After explicit confirmation of this exact list, execute the guarded cleanup script below. It refuses changed project membership or labels. It preserves every volume, network and image.

```sh
python3 deploy/komodo/cleanup_old.py --confirmed-downtime
```

Never use `down -v`, volume removal, or broad prune. Keep the old images for rollback. Registry, Komodo, Colima, shared networks and other stacks are excluded.

## Verification after deployment

```sh
curl -fsS http://127.0.0.1:8088/frontend-health
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/ready
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:9090/api/v1/targets
curl -fsS http://127.0.0.1:1900/api/health
docker --context colima ps --filter label=com.docker.compose.project=android-fleet
```

Open frontend `http://127.0.0.1:8088`, authenticate with existing credentials, verify all five device registrations, Samsung reconnect using its existing Wireless Debugging connect endpoint, historical telemetry, 8 alert rules and existing events, control operations and audit history. Pairing ports differ from connect ports and may change when Wireless Debugging restarts. Do not re-pair unless the device requires it. Inspect ADB key filenames/permissions without printing contents. Check Prometheus target `android-manager:8000` is UP and Grafana provisioned dashboards, including streaming, load.

Start Samsung screen streaming through the frontend as an authorized user; verify frames and permitted controls, end session, and check resource cleanup. Test viewer/operator/admin restrictions per `docs/AUTHORIZATION.md`, unauthenticated API rejection, and forbidden WebSocket origins. Use browser UI to keep tokens out of shell logs. Compare database table counts with private snapshot inventory; history retention may legitimately reduce old counts. Confirm persistence after a deliberate backend recreation through Komodo. Hardware streaming and persistence after deployment have **not** been tested by this preparation.

Loopback remains the intended entry point. Do not publish these services to the public internet. Colima port forwarding must be checked from another LAN machine before claiming LAN isolation; no networking settings were changed here.

## Updates and rollback

```sh
cd /Users/homelab/Development/adb-dashboard
version=$(git rev-parse --short HEAD)
docker --context colima build --platform linux/arm64 -f docker/Dockerfile -t "mac.lab:5000/android-fleet/backend:$version" .
docker --context colima build --platform linux/arm64 -f docker/frontend.Dockerfile -t "mac.lab:5000/android-fleet/frontend:$version" .
for service in backend frontend; do
  docker --context colima tag "mac.lab:5000/android-fleet/$service:$version" "192.168.123.238:5000/android-fleet/$service:$version"
  docker --context colima push "192.168.123.238:5000/android-fleet/$service:$version" || exit 1
  docker --context colima tag "192.168.123.238:5000/android-fleet/$service:$version" "192.168.123.238:5000/android-fleet/$service:latest"
  docker --context colima push "192.168.123.238:5000/android-fleet/$service:latest" || exit 1
  curl -fsS -D - -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' "http://mac.lab:5000/v2/android-fleet/$service/manifests/$version" || exit 1
done
```

Record digests and architecture for each version, back up SQLite before redeployment, replace Stack image environment values with new digest references, Save and Deploy, then repeat verification. Existing HEAD is dirty; the prepared SHA tag includes uncommitted changes and is not reproducible from Git alone. Do not overwrite the same version tag for different working-tree content; use a unique SHA-plus-build timestamp suffix if HEAD has not changed. No new commit is required by this procedure.

To roll back, restore the previous image digest values, Save and Deploy. Keep the same external volumes. If a later version migrates schemas, verify backwards compatibility first; restoring a database backup is a separate downtime operation and loses data collected after that backup. Old backend image `adb-dashboard-android-manager` and frontend `adb-dashboard-frontend` were retained.

## Troubleshooting

- Registry resolution: `colima ssh -- getent hosts mac.lab`; `docker exec komodo-periphery-1 getent hosts mac.lab`. Both resolved `192.168.123.238` during preflight. Container/VM DNS can differ from macOS.
- HTTP trust: hostname pulls currently fail. Use the verified trusted-IP override, or schedule an approved daemon change; do not alter global configuration automatically.
- Connectivity: confirm context `colima`, registry `/v2/`, daemon reachability and current LAN IP. Do not modify Colima networking to fix ADB discovery.
- Missing volumes: inspect all four exact names; wrong server/context can make them appear absent. Never create blank substitutes or delete originals.
- Permissions: fleet UID 10001, Grafana UID 472/GID 0, Prometheus UID/GID 65534. Inspect ownership through a read-only helper; avoid recursive ownership changes on shared data.
- ADB: direct device Wi-Fi address/connect port must be reachable from the backend container. mDNS may not cross Colima bridges. Confirm Wireless Debugging, pairing trust and Wi-Fi; port 5037 remains internal.
- WebSocket failures: nginx routes `/api/` to `android-manager:8000`, forwards Authorization, Origin and Upgrade headers. Service name must remain `android-manager`; origins must match exactly. Idle timeout and screen quotas are environment settings.
- scrcpy: verify `/opt/scrcpy/scrcpy-server` SHA256 `8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e`, version 3.3.4, Android compatibility, ADB authorization and backend session logs. Do not install a management APK.
- Port conflicts: old containers must be removed only after confirmation; identify the precise listener before stopping anything.
- Stack files: paths used by Periphery are container/VM paths. Use UI-written files under `/etc/komodo/stacks/android-fleet`; never assume it can read macOS repository files. Monitoring mounts are daemon-side verified absolute paths.

## M7 terminal preparation

Compose adds default-disabled ADB terminal, a default-empty SSH destination allowlist, and
Wireless Debugging network approvals managed in the dashboard (with an optional first-start
environment seed), terminal limits/Origins and a separately supplied SSH encryption key.
Pairing approvals persist in `pairing.sqlite3`, inside the existing data volume and included
automatically in database backups. Existing external
volumes, image names and ports are retained. No SSH daemon/socket mount/privilege needed.
Before approved rollout back up every active SQLite database and ADB credentials, and
keep the SSH encryption key backup separately. M7 versioned local images can be prepared
as `mac.lab:5000/android-fleet/backend:m7-*` and frontend equivalents. Registry publication
does not deploy the images; obtain separate approval before changing the running stack.
Resolve pushed immutable digests before updating image variables.
Existing localhost:5000 tags/digests are not silently rewritten. See
[M7 configuration](../../docs/M7_SSH_CONFIGURATION.md).
