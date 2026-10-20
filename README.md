# Android Fleet Manager

An early-stage, capability-driven platform for centralized Android monitoring and management through authenticated ADB. Rooted and non-rooted devices share the same platform without a monitoring agent, management APK or SSH server. M0 establishes the foundation; M1 adds persistent registration, discovery and connectivity; M2 adds real monitoring and bounded history; M3 adds the web dashboard and persistent server-side alerting. This is not production-ready infrastructure.

```text
Android devices → authenticated ADB → Android Manager → snapshots → Prometheus → Grafana
React Dashboard → REST → Android Manager → ADB → devices
Android Manager → alert evaluation → SQLite rules/events
```

**School assignment (CZ):** root-aware monitoring (ZRAM, GPU, processes, CPU frequency capping, battery capacity, device info), Grafana fleet/device views, phone preparation and small-VM deployment are described in [docs/SCHOOL_ASSIGNMENT.md](docs/SCHOOL_ASSIGNMENT.md); run and test instructions are in [NAVOD.md](NAVOD.md).

Rooted devices may use fixed-port TCP ADB and authorized su. Non-rooted devices may use Wireless Debugging/TLS pairing or USB. Connection method does not establish capabilities: bounded probes observe supported operations independently. Battery, CPU, RAM, storage, network, uptime and available thermal monitoring are implemented. Vendor collectors, terminals and arbitrary command execution remain deferred.

## Local development

Install Python 3.13+ and run from the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'backend[dev]'
ANDROID_FLEET_FAKE_ADB=true uvicorn android_fleet.main:app --reload --host 127.0.0.1 --no-proxy-headers
```

Fake mode can seed four registered demo devices: rooted Pixel-like, stock Pixel-like, offline and malformed-output. It contacts no hardware. Set `ANDROID_FLEET_FAKE_ADB=false` to use the configured ADB server; discovered devices require explicit registration. Real registrations receive UUIDs; demo seed IDs preserve M0 serial labels. A SQLite registry preserves stable IDs and connection configuration separately from observed state and capabilities. Manual disconnect disables automatic reconnection until connect or a configuration update enables it again.

Configuration variables are in [.env.example](.env.example). Local Python reads exported environment variables; Compose reads `.env`. Optional mDNS discovery is best effort and associates dynamic connect ports with an exact configured service name. Pairing advertisements remain visible as pairing-required; pairing itself is operator-managed.

Read-only routes include `/health`, `/ready`, `/api/v1/devices`, `/api/v1/discovery/devices` and `/metrics`. Registration, connection and capability-refresh routes are documented in [API conventions](docs/API.md); generated schemas are at `/docs`. Server-side role permissions guard protected reads and controls by default; no tokenless loopback mutations are permitted. See [authorization](docs/AUTHORIZATION.md) for named credentials and optional private reads.

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy src
```

## Docker development

```bash
cp .env.example .env
# Set a Grafana password and a control token before HTTP mutations through Docker.
docker compose config --quiet
docker compose build android-manager frontend
docker compose up -d
```

Use `docker-compose` if the Docker CLI plugin is unavailable. Web dashboard: http://127.0.0.1:8088, Manager: http://127.0.0.1:9000, Prometheus: http://127.0.0.1:9090, Grafana: http://127.0.0.1:1900 (admin and the configured password). A Prometheus datasource and fleet/device dashboards are provisioned in the Android Fleet folder. Volumes preserve the registry, telemetry, alerts, Grafana data and sensitive ADB trust keys. The container registry path is `/var/lib/android-fleet/devices.sqlite3`. Never commit `.env`, registry data or keys.

Docker forwards HTTP from a nonloopback peer, so set `ANDROID_FLEET_CONTROL_TOKEN` for mutation requests even when the published host port is loopback. Network ADB is the deployment assumption. USB passthrough and multicast discovery differ across Linux, macOS Docker Desktop, Colima and Windows; this stack does not provide universal USB passthrough. See [ADB setup](docs/ADB_SETUP.md).

## Continue development

Read [AGENTS.md](AGENTS.md), [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), [API conventions](docs/API.md), [metrics](docs/METRICS.md), [development](docs/DEVELOPMENT.md) and [roadmap](ROADMAP.md) before extending contracts. M4 adds role authorization, persistent audit and bounded device control. M4.5 hardens authenticated reads and session handling; see [M4.5 validation](docs/M4_5_VALIDATION.md) for acceptance limits. Owner license selection is pending; [LICENSE](LICENSE) reserves rights until that decision.

Automated tests need no Android hardware. Production hardening and broader hardware validation remain outstanding. No commits, pushes or GitHub repository creation are performed automatically.

M1 validation: **160 tests passed**, Ruff lint/format and mypy passed, Compose configuration/build and isolated restart/persistence checks passed. See [validation record](docs/M1_VALIDATION.md); real Pixel acceptance remains pending.

M2 adds independent bounded metrics polling, current/history REST endpoints, seven-day/one-million-point SQLite history in the existing private volume, and fleet/device dashboards. See [metrics](docs/METRICS.md) and [M2 validation](docs/M2_VALIDATION.md).

M2 validation: **261 tests passed**, Ruff/mypy and Compose config/build passed. Real non-rooted SM-A356B (registered as “Pixel”) telemetry, Prometheus, dashboard provisioning, registration/history persistence and automatic reconnection after backend restart were verified. Actual Google Pixel and rooted hardware acceptance remain unverified.

M3 provides fleet search/filter/sort, current and historical device pages, authenticated
registration/reconnect management, dark/light themes and alert configuration,
acknowledgement and history. Enter a control token only for the current tab session;
the UI never stores it in browser storage. See [frontend setup](frontend/README.md),
[alert configuration](docs/ALERTING.md), [deployment](docs/DOCKER.md) and
[M3 validation](docs/M3_VALIDATION.md) for actual checks and acceptance limits.

### Switch a paired device to ADB TCP

After pairing, connecting and registering a Wireless Debugging device, an administrator
can click **Switch to ADB TCP** in its device page or Device management. Confirm
**Enable TCP and reconnect** to enable port 5555, verify the same Android serial,
and update the existing registration while preserving its ID, name and history.
The device must be online with ADB shell capability and its private IP must be
approved in Wireless Debugging network access. No root, APK or manual command is required.

Switching may close active shells. TCP mode may need enabling again after reboot;
use only trusted networks. If enabling, reconnecting or identity verification fails,
the original registration remains unchanged and stale observations are invalidated.
Reconnect Wireless Debugging before retrying. If port 5555 already has a separate
registration, remove the duplicate before switching.

After changing transport, the switch waits briefly for the full shell capability
probe to recover from an ADB restart. If the verified TCP endpoint is saved but
the shell remains unavailable, the error explicitly says TCP is enabled and asks
you to click **Reconnect**; pairing again is unnecessary.

### Optional F-Droid, Termux and SSH setup

Administrators can open a device page and choose **Install F-Droid, Termux & SSH**.
Confirm the operation and leave the phone unlocked with Termux in the foreground.
Approve Android's initial prompts and let the first Termux shell finish opening.
The queued operation displays progress in Device Control. If initialization or a
permission prompt interrupted it, open an idle Termux shell and choose
**Enable Termux SSH** to resume without reinstalling apps or typing commands.

Setup installs missing apps from checksum-pinned official F-Droid artifacts:
F-Droid 1.23.2 and Termux 0.118.3. Existing apps and data are preserved; setup never
uninstalls conflicting APK signatures. Termux's universal APK is approximately
109 MiB, so this fixed catalog uses a separate 128 MiB bound without increasing
the general APK upload limit. Downloads require backend internet access; OpenSSH
package installation also requires internet on the device. No helper APK,
external-app command permission or root is used. Primary Android user 0 and a
container-local ADB server are currently required.

Configure the existing `ANDROID_FLEET_SSH_ENCRYPTION_KEY` with a persistent Fernet
key before using setup. Managed Ed25519 private keys are encrypted by the existing
SSH profile store and reused on retries. Setup explicitly authorizes only that
device's private IP on TCP 8022. It configures public-key-only SSH and restarts
Termux SSH, closing its existing sessions. ADB establishes the host-key trust
anchor before a real key-authenticated LAN login is verified. Only then is the
SSH profile enabled; select **Termux SSH · device name** in the Terminal panel
(the list refreshes within ten seconds).

The setup script is typed into Termux through authenticated ADB. Do not type or
switch apps while it runs. Commands are submitted only while Termux owns the
foreground window. Input is paced in small chunks to avoid losing the end of long
commands in the terminal input queue. Work is serialized with other per-device control operations,
has a ten-minute default budget (overridable with `setup.termux` / `setup.ssh` in
`ANDROID_FLEET_OPERATIONS_TIMEOUTS`), and is not replayed after backend restart.
Partial app installations or a running device-side script may remain after an
interruption; retrying reuses the managed key. SSH is optional and independent
of all fleet monitoring. Android can stop Termux in the background or after reboot;
boot-time startup and battery-policy changes are not configured by this feature.

Artifact metadata: https://f-droid.org/repo/index-v2.json; upstream setup details:
https://github.com/termux/termux-app#installation and
https://github.com/termux/termux-packages/tree/master/packages/openssh.

### Persistent terminals and SSH program recordings

Terminal sessions remain on the backend when you close a browser or navigate away.
Open the terminal workspace and use **Sessions and recorded results → Resume session**
to reconnect; **Close session** in that list explicitly terminates the remote shell
and frees a session slot. Detached shells still count toward session limits. Sessions still
end on backend restart/shutdown, revoked authorization, connection loss, or the
configured maximum session lifetime. Attached interactive shells also retain the
configured idle timeout. Output is buffered in memory (last 65,536 characters);
slow clients may miss older output instead of terminating the remote program.

Choose an SSH connection, enter a **Program command**, and select **Record run**.
The approved SSH host must provide GNU `time` with `-v` and `sh`. Its final report
includes CPU utilization, user/system CPU seconds, elapsed time, maximum resident
RAM (KiB), I/O and exit status for the command and its waited-for children. This is
a whole-run resource summary, not a sampled CPU/RAM timeline or device-wide metric.
Unsupported `time` implementations report their error in the saved output; missing
observations are not filled with zeros. Background processes that outlive the command
are outside the report.

Recorded commands and their last 65,536 output characters are saved to the terminal
SQLite database and remain available in session history after backend restart. Use
**Download results** to save the report as text. Command/output can contain secrets;
record only content appropriate to retain on the backend. Interactive shell output
is not stored on disk. An interrupted run may have partial output without a final
resource report; consult the session state and termination reason.

For device-wide charts alongside a program run, leave **Record device statistics
(15 seconds)** enabled on an SSH profile linked to an online Android device. Expand
the run for CPU per core, overall CPU, RAM, thermal sensors and supported GPU/NPU
readings, or select it in the device page's **Historical telemetry → Program run
charts**. Download the timestamped readings as CSV. Default metric collection and
chart refresh are 15 seconds. Unsupported accelerator readings remain unavailable;
see [recording details and limits](docs/METRICS.md#device-statistics-during-program-runs).
