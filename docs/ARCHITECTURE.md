# Architecture

Monitoring: Android device → authenticated ADB → Android Manager → capability-gated collectors → normalized snapshots → Prometheus exporter → Prometheus → Grafana.

M4 device control: React → permission-enforced REST → persistent operation manager → AdbClient → device. SecurityService owns identities and a separate SQLite audit database. Operations persist before dispatch, serialize per device and share a global concurrency bound. No arbitrary shell, terminal or Android agent is exposed.

## Decision: container-owned ADB on macOS

The default is **B: ADB server inside Android Manager**, with RSA/TLS trust files in the existing adb-keys volume. Port 5037 is container-local and never published; connections go outbound through the container/VM to devices. Backend commands and operator pairing use the same trust identity across restarts. SQLite has a separate private device-registry volume.

| Option | Benefits | Costs and decision |
| --- | --- | --- |
| A: macOS host server | Native USB and LAN mDNS visibility | Its unauthenticated server protocol must cross a VM boundary. Host loopback reachability differs by runtime; broad listeners expose privileged access. Operator-managed secured alternative only. |
| B: container server | Isolated ownership, persistent keys, no exposed server port, predictable network TCP behavior | Bridged multicast/USB limitations; explicit IP/port is the fallback. Selected default. |

Do not enable adb -a or publish 5037. External ADB_SERVER_HOST/PORT remain available only for a separately secured private server/tunnel with independently tested routing. Neither host.docker.internal nor host networking is assumed. Colima and Docker Desktop do not provide identical USB or multicast behavior. See [Colima configuration](https://colima.run/docs/configuration/) and [ADB Wi-Fi architecture](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md).

ADB's own mDNS auto-connect is disabled (`ADB_MDNS_AUTO_CONNECT=0`) so the manager controls reconnect intent. A separately running external server must use the same policy; setting the variable only on an external client cannot change that server. USB transport remains physically attached after a logical manager disconnect, but is neither probed nor exported as online.

## Boundaries

| Module | Responsibility |
| --- | --- |
| devices/registry_models.py | Transport-independent registration/configuration contracts |
| devices/registry.py | SQLite validation, schema/versioning, transactions and persistence |
| devices/models.py | Disposable device observations, operational states, capabilities |
| adb/base.py | All ADB operations through a mockable async protocol |
| adb/subprocess.py, fake.py | Safely quoted argv/process timeouts and deterministic fake transport |
| adb/connection.py | Per-device lock, endpoint reconciliation, bounded jitter/backoff and safe connection errors |
| discovery | Read-only transport/mDNS snapshots and exact identity association |
| devices/probe.py | Bounded read-only property/root/metric-support observations |
| devices/service.py | Lifecycle orchestration, serialized polling/control/configuration changes |
| collectors | Modular battery/CPU/RAM/storage/network/uptime/thermal observations, no API/exporter dependencies |
| metrics | Validated typed snapshots, bounded SQLite history and explicit Prometheus names/units/labels |
| api, core, main.py | Versioned schemas, settings, mutation guard, lifespan and HTTP transport |
| execution | Internal argv/result contracts; public execution deferred |

Shared interfaces are coordinator-owned. Registry, ADB manager, discovery/probing and integration/test workstreams have bounded ownership. Device-specific collectors extend the explicit hardware collector protocol. Root is observed, not assumed from connection type; unsupported capabilities/metrics remain absent.

## Identity, persistence and runtime state

Registry-generated UUIDs survive changes in ADB serials and wireless ports. Configuration includes friendly name, connection type, endpoint or USB serial, optional exact wireless mDNS connect instance, string metadata, auto-connect intent and UTC timestamps. Demo-only seed IDs retain M0 serial labels. The SQLite schema stores no online state, capabilities, metrics or secrets. Its last_connected_at timestamp is historical and never establishes ONLINE.

Schema version 1 uses PRAGMA user_version, transactional initialization, endpoint/serial/service uniqueness, WAL and bounded lock waits. Future migrations must be explicit, ordered transactions; newer unsupported schemas fail rather than downgrade. A thread lock serializes one connection; asyncio.to_thread keeps disk I/O off the event loop. Canceled SQLite operations finish before releasing service locks or closing the connection. HTTP PATCH merges under the service lock to prevent lost configuration updates.

Startup opens SQLite, loads registration and reevaluates connectivity. Real discovery never auto-registers. ADB listing must confirm an authorized transport before ONLINE; successful connect exit status alone is insufficient. Unauthorized, offline, pairing-required, connecting/reconnecting, error, unavailable and intentionally disconnected states are distinct. Manual disconnect persists auto_connect=false before attempting transport teardown; reconnect resumes only through explicit connect or configuration reenable. Failed teardown is reported safely while probing/metrics remain disabled.

Each app owns its registry, client, discovery, connection manager, observations and worker. Per-device locks prevent duplicate ADB connection attempts. Bounded exponential backoff with jitter is reevaluated at the poll interval; authorization failures avoid rapid retries. Exact mDNS identity can replace a wireless endpoint when discovery works. Missing multicast preserves the last known endpoint or configured manual fallback; an advertisement never grants trust. Pairing is manual and separate from connect.

Fresh probes refresh capabilities after reconnection. Unavailable metrics cannot stop other collectors. Snapshots replace stale samples; disconnected devices have android_device_up=0 and no current root/battery/memory samples. HTTP scrapes read snapshots, never poll hardware. Readiness reflects registry/polling/ADB infrastructure, not whether any phone is online. Shutdown cancels/reaps subprocess work, drains SQLite operations and closes storage.

## Limits and extension points

One backend worker owns the fleet; multiple worker processes would each schedule connections and are not supported by M1. Polling and control operations are serialized; large fleets need bounded parallel scheduling later. Runtime last-known dynamic endpoints/backoff are not persisted; after restart absent multicast requires a current manual port. No Android hardware, USB passthrough or cross-VM multicast success is assumed from fake tests.

M4 supplies per-actor fleet-wide operation permissions, audit records, bounded jobs and safe local cancellation. Per-device scopes and interactive streaming/backpressure remain deferred. The tokenless direct-peer exemption has been removed. Collectors/domain models remain independent of FastAPI, SQLite formats and Prometheus. Configuration formats must produce domain models rather than leak transport dictionaries into services.

## M2 monitoring and history

Connectivity and metrics run as separately owned background workers. Metrics commands run through the async ADB interface with per-command and whole-device budgets. A fleet semaphore bounds concurrent device collection; one task per device prevents overlap. Reconnect/disconnect increments a generation, cancels old collection, clears current telemetry and resets CPU delta baselines. Publishing checks generation, serial and online state, preventing late observations from resurrecting disconnected devices. Slow collectors do not hold the connectivity/configuration lock.

Collectors return partial typed snapshots. A domain catalog validates units, finite values, ranges and bounded dimensions; the exporter alone translates to Prometheus names. CPU needs two counter samples; unsupported sources are omitted. Capability observations refresh after reconnect and periodically rather than repeating root probes every metrics interval.

History uses a separate schema-versioned SQLite file, `metrics.sqlite3`, in the existing private registry volume. Registry configuration and keys are untouched. Async wrappers serialize SQLite transactions in worker threads and drain operations on cancellation. Indexed device/time and device/metric/time queries use bounded cursor pagination. Seven-day retention and a one-million-point global cap apply by default; eviction reuses allocated pages rather than guaranteeing file shrinkage. Startup and periodic pruning also handle an idle fleet. Prometheus retains its independent time-series database.
