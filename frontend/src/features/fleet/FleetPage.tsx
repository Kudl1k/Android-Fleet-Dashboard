import { memo, useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, Cable, ListChecks, Plus, Search, ShieldAlert, Smartphone, Thermometer, Wifi } from "lucide-react";
import BulkActions, { useBulkAllowed } from "./BulkActions";
import { conditionLabel, useFiringAlerts } from "../../lib/alertNotifications";
import Meter from "../../components/Meter";
import PhoneGlyph from "../../components/PhoneGlyph";
import { useDevices, useMetrics, useTrend } from "../../lib/hooks";
import { formatMetric, isAccessError, metricValue, OPEN_ACCESS_EVENT, type Device } from "../../lib/api";
import { relativeTime, useNow } from "../../lib/time";
import { fleetGroup } from "./fleetState";
export { fleetGroup };
export const groupLabels: Record<string, string> = {
    total: "All devices",
    online: "Online",
    offline: "Offline",
    degraded: "Needs attention",
};
export function filterDevices(
    devices: Device[],
    search: string,
    state: string,
    sort: string,
) {
    return devices
        .filter(
            (d) =>
                (state === "all" || fleetGroup(d) === state) &&
                `${d.name} ${d.manufacturer ?? ""} ${d.model ?? ""} ${d.host ?? ""}`
                    .toLowerCase()
                    .includes(search.toLowerCase()),
        )
        .sort((a, b) =>
            sort === "last_seen"
                ? (b.last_seen ?? "").localeCompare(a.last_seen ?? "")
                : sort === "state"
                  ? a.state.localeCompare(b.state)
                  : a.name.localeCompare(b.name),
        );
}
function deviceIssue(device: Device): string {
    if (device.state === "unauthorized")
        return device.error_message ?? "Accept the RSA key prompt on the device.";
    const reason = device.error_message ?? "Not connected";
    return device.retry_in_seconds !== null
        ? `${reason}. Retrying in ${device.retry_in_seconds} s.`
        : reason;
}
export const DeviceCard = memo(function DeviceCard({
    device,
    selectable = false,
    selected = false,
    onToggle,
}: {
    device: Device;
    selectable?: boolean;
    selected?: boolean;
    onToggle?: (id: string) => void;
}) {
    const metrics = useMetrics(device.id);
    const alerts = useFiringAlerts().data?.filter((alert) => alert.device_id === device.id) ?? [];
    const trend = useTrend(device.id, "cpu_usage", device.state === "online");
    const now = useNow();
    const group = fleetGroup(device);
    const current = device.state === "online" && !metrics.isError ? metrics.data : undefined;
    const ram = metricValue(current, "memory_used");
    const total = metricValue(current, "memory_total");
    const battery = metricValue(current, "battery_level");
    const charging = metricValue(current, "battery_charging");
    const cpu = metricValue(current, "cpu_usage");
    const temperature = metricValue(current, "thermal_temperature");
    const ramRatio = ram !== null && total !== null && total > 0 ? ram / total : null;
    const storageUsed = metricValue(current, "storage_used");
    const storageTotal = metricValue(current, "storage_total");
    const storageRatio =
        storageUsed !== null && storageTotal !== null && storageTotal > 0 ? storageUsed / storageTotal : null;
    return (
        <div className="device-slot" data-selected={selected || undefined}>
        {selectable && (
            <label className="device-select" title={group === "online" ? undefined : "Only online devices accept actions"}>
                <input
                    type="checkbox"
                    checked={selected}
                    disabled={group !== "online"}
                    onChange={() => onToggle?.(device.id)}
                />
                <span className="sr-only">Select {device.name}</span>
            </label>
        )}
        <Link className="device-card panel" data-group={group} data-alert={alerts.length ? alerts.some((a) => a.severity === "critical") ? "critical" : "warn" : undefined} to={`/devices/${encodeURIComponent(device.id)}`}>
            <PhoneGlyph group={group} battery={battery} charging={charging === 1} />
            <span className="sr-only">
                Battery {formatMetric(battery, "ratio")}
                {charging === 1 ? ", charging" : charging === 0 ? ", not charging" : ""}
            </span>
            <div className="device-card-body">
                <div className="device-card-head">
                    <h2>{device.name}</h2>
                    <span className={`state-pill ${group}`}>
                        <i className={`led ${group}`} aria-hidden="true" />
                        {device.state.replaceAll("_", " ")}
                    </span>
                </div>
                <p className="device-identity">
                    {[device.manufacturer, device.model]
                        .filter(Boolean)
                        .join(" ") || "Identity unavailable"}
                    <span> · Android {device.android_version ?? "—"}</span>
                </p>
                <ul className="device-tags" aria-label="Connection and access">
                    <li>
                        {device.host ? <Wifi size={13} aria-hidden="true" /> : <Cable size={13} aria-hidden="true" />}
                        {device.host
                            ? `${device.host}${device.port ? `:${device.port}` : ""}`
                            : device.connection_type.toUpperCase()}
                    </li>
                    <li>
                        {device.root_available === null
                            ? "Root unknown"
                            : device.root_available
                              ? "Root available"
                              : "Non-rooted"}
                    </li>
                    {temperature !== null && (
                        <li>
                            <Thermometer size={13} aria-hidden="true" />
                            {formatMetric(temperature, "celsius")}
                        </li>
                    )}
                </ul>
                {alerts.length > 0 && (
                    <p className="device-alert">
                        <Bell size={14} aria-hidden="true" />
                        {alerts.length === 1
                            ? `Alert: ${conditionLabel(alerts[0].condition)}`
                            : `${alerts.length} alerts firing`}
                    </p>
                )}
                {group !== "online" && (
                    <p className="device-issue">
                        <ShieldAlert size={14} aria-hidden="true" />
                        {deviceIssue(device)}
                    </p>
                )}
                <div className="card-metrics">
                    <Meter label="CPU" value={cpu} display={formatMetric(cpu, "ratio")} trend={cpu === null ? undefined : trend.data} />
                    <Meter label="RAM" value={ramRatio} display={formatMetric(ramRatio, "ratio")} />
                    <Meter label="Storage" value={storageRatio} display={formatMetric(storageRatio, "ratio")} />
                </div>
                <p className="card-footer">
                    <span>
                        {metrics.isError
                            ? "Telemetry unavailable"
                            : metrics.data?.stale
                              ? "Telemetry stale"
                              : device.state !== "online"
                                ? "Disconnected — telemetry unavailable"
                                : metrics.data?.observed_at &&
                                    metrics.data.values.length
                                  ? "Live telemetry"
                                  : "Waiting for telemetry"}
                    </span>
                    <span title={device.last_seen ? new Date(device.last_seen).toLocaleString() : undefined}>
                        Seen {relativeTime(device.last_seen, now)}
                    </span>
                </p>
            </div>
        </Link>
        </div>
    );
});
export default function FleetPage() {
    const devices = useDevices();
    const [search, setSearch] = useState("");
    const [state, setState] = useState("all");
    const [sort, setSort] = useState("name");
    const bulkAllowed = useBulkAllowed();
    const [selecting, setSelecting] = useState(false);
    const [selected, setSelected] = useState<Set<string>>(() => new Set());
    const toggle = useCallback((id: string) => {
        setSelected((old) => {
            const next = new Set(old);
            if (!next.delete(id)) next.add(id);
            return next;
        });
    }, []);
    const selectedDevices = (devices.data ?? []).filter(
        (device) => selected.has(device.id) && fleetGroup(device) === "online",
    );
    const visible = useMemo(
        () => filterDevices(devices.data ?? [], search, state, sort),
        [devices.data, search, state, sort],
    );
    const counts = useMemo(() => {
        if (!devices.data) return null;
        const result: Record<string, number> = { total: devices.data.length, online: 0, offline: 0, degraded: 0 };
        for (const device of devices.data) result[fleetGroup(device)]++;
        return result;
    }, [devices.data]);
    return (
        <>
            <div className="page-heading">
                <div>
                    <h1>Fleet overview</h1>
                    <p className="muted">
                        Every phone on the bench, observed through authenticated
                        ADB.
                    </p>
                </div>
                <Link className="button primary" to="/management">
                    <Plus size={17} aria-hidden="true" /> Register device
                </Link>
            </div>
            <section className="fleet-health panel" aria-label="Fleet status">
                <div className="health-counts">
                    {["total", "online", "degraded", "offline"].map((group) => (
                        <button
                            type="button"
                            className="health-count"
                            data-group={group}
                            aria-pressed={state === (group === "total" ? "all" : group)}
                            key={group}
                            onClick={() => setState(group === "total" ? "all" : group)}
                        >
                            <span>
                                {group !== "total" && <i className={`led ${group}`} aria-hidden="true" />}
                                {groupLabels[group]}
                            </span>
                            <strong>{counts ? counts[group] : "—"}</strong>
                        </button>
                    ))}
                </div>
                {counts && counts.total > 0 && (
                    <div
                        className="health-bar"
                        role="img"
                        aria-label={`${counts.online} online, ${counts.degraded} need attention, ${counts.offline} offline`}
                    >
                        {(["online", "degraded", "offline"] as const).map((group) =>
                            counts[group] ? (
                                <span key={group} className={group} style={{ flexGrow: counts[group] }} />
                            ) : null,
                        )}
                    </div>
                )}
            </section>
            <div className="toolbar">
                <label className="search" htmlFor="device-search">
                    Search devices
                    <span className="search-input"><Search size={17} aria-hidden="true" /><input
                        id="device-search"
                        name="device-search"
                        type="search"
                        placeholder="Name, model or IP address"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    /></span>
                </label>
                <label>
                    Connection
                    <select
                        value={state}
                        onChange={(e) => setState(e.target.value)}
                    >
                        <option value="all">All devices</option>
                        <option value="online">Online</option>
                        <option value="offline">Offline</option>
                        <option value="degraded">Needs attention</option>
                    </select>
                </label>
                <label>
                    Sort by
                    <select
                        value={sort}
                        onChange={(e) => setSort(e.target.value)}
                    >
                        <option value="name">Device name</option>
                        <option value="state">Connection state</option>
                        <option value="last_seen">Last seen</option>
                    </select>
                </label>
            </div>
            <div className="results-heading">
                <h2>Devices</h2>
                <span className="muted" role="status">{devices.data ? `${visible.length} of ${devices.data.length} devices` : "Awaiting fleet data"}</span>
                {bulkAllowed.length > 0 && !selecting && (
                    <button type="button" className="select-toggle" onClick={() => setSelecting(true)}>
                        <ListChecks size={16} aria-hidden="true" /> Select devices
                    </button>
                )}
            </div>
            {selecting && (
                <BulkActions
                    devices={selectedDevices}
                    onClear={() => {
                        setSelecting(false);
                        setSelected(new Set());
                    }}
                />
            )}
            {devices.isPending ? (
                <div className="device-grid" role="status" aria-label="Loading devices">
                    {[1, 2, 3].map((n) => (
                        <div className="panel skeleton" key={n} />
                    ))}
                </div>
            ) : devices.isError && isAccessError(devices.error) ? (
                <div className="panel empty">
                    <ShieldAlert size={36} aria-hidden="true" />
                    <h2>Sign in to view your fleet</h2>
                    <p className="muted">
                        Device data needs a viewer, operator or administrator token.
                    </p>
                    <button onClick={() => window.dispatchEvent(new Event(OPEN_ACCESS_EVENT))}>
                        Sign in
                    </button>
                </div>
            ) : devices.isError ? (
                <div className="panel error" role="alert">
                    <h2>Could not load the fleet</h2>
                    <p>{devices.error.message}</p>
                    <button onClick={() => void devices.refetch()}>
                        Try again
                    </button>
                </div>
            ) : visible.length ? (
                <div className="device-grid">
                    {visible.map((device) => (
                        <DeviceCard
                            device={device}
                            key={device.id}
                            selectable={selecting}
                            selected={selected.has(device.id)}
                            onToggle={toggle}
                        />
                    ))}
                </div>
            ) : (
                <div className="panel empty">
                    <Smartphone size={36} aria-hidden="true" />
                    <h2>
                        {devices.data?.length
                            ? "No matching devices"
                            : "Your fleet is ready for its first device"}
                    </h2>
                    <p className="muted">
                        {devices.data?.length
                            ? "Try a different search or connection filter."
                            : "Register an already authorized device to start monitoring."}
                    </p>
                    {devices.data?.length ? <button onClick={() => { setSearch(""); setState("all"); }}>Clear filters</button> : <Link className="button" to="/management"><Plus size={17} aria-hidden="true" /> Register device</Link>}
                </div>
            )}
        </>
    );
}
