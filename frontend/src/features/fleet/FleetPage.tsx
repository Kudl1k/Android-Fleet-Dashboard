import { memo, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Smartphone } from "lucide-react";
import { useDevices, useMetrics } from "../../lib/hooks";
import { formatMetric, metricValue, type Device } from "../../lib/api";
export function fleetGroup(device: Device): string {
    if (device.state === "online") return "online";
    return ["offline", "disconnected"].includes(device.state)
        ? "offline"
        : "degraded";
}
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
export const DeviceCard = memo(function DeviceCard({
    device,
}: {
    device: Device;
}) {
    const metrics = useMetrics(device.id);
    const current = device.state === "online" && !metrics.isError ? metrics.data : undefined;
    const ram = metricValue(current, "memory_used");
    const total = metricValue(current, "memory_total");
    return (
        <Link className="device-card panel" to={`/devices/${encodeURIComponent(device.id)}`}>
            <div className="row">
                <div className="device-icon">
                    <Smartphone size={22} />
                </div>
                <span className={`badge ${fleetGroup(device)}`}>
                    {device.state.replaceAll("_", " ")}
                </span>
                <ArrowUpRight size={18} className="muted" />
            </div>
            <h2>{device.name}</h2>
            <p className="muted">
                {[device.manufacturer, device.model]
                    .filter(Boolean)
                    .join(" ") || "Identity unavailable"}
            </p>
            <div className="device-meta">
                Android {device.android_version ?? "—"} ·{" "}
                {device.root_available === null
                    ? "Root unknown"
                    : device.root_available
                      ? "Root available"
                      : "Non-rooted"}
            </div>
            <div className="card-metrics">
                <div>
                    <span>Battery</span>
                    <strong>
                        {formatMetric(
                            metricValue(current, "battery_level"),
                            "ratio",
                        )}
                    </strong>
                    <small>
                        {metricValue(current, "battery_charging") === null
                            ? "Charging unavailable"
                            : metricValue(current, "battery_charging") ===
                                1
                              ? "Charging"
                              : "Not charging"}
                    </small>
                </div>
                <div>
                    <span>CPU</span>
                    <strong>
                        {formatMetric(
                            metricValue(current, "cpu_usage"),
                            "ratio",
                        )}
                    </strong>
                </div>
                <div>
                    <span>RAM</span>
                    <strong>
                        {formatMetric(
                            ram !== null && total !== null && total > 0
                                ? ram / total
                                : null,
                            "ratio",
                        )}
                    </strong>
                </div>
            </div>
            <p className="card-footer">
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
                <span>
                    Seen{" "}
                    {device.last_seen
                        ? new Date(device.last_seen).toLocaleString()
                        : "never"}
                </span>
            </p>
        </Link>
    );
});
export default function FleetPage() {
    const devices = useDevices();
    const [search, setSearch] = useState("");
    const [state, setState] = useState("all");
    const [sort, setSort] = useState("name");
    const visible = useMemo(
        () => filterDevices(devices.data ?? [], search, state, sort),
        [devices.data, search, state, sort],
    );
    return (
        <>
            <div className="page-heading">
                <div>
                    <p className="eyebrow">FLEET MONITORING</p>
                    <h1>Fleet overview</h1>
                    <p className="muted">
                        Your Android devices, observed through authenticated
                        ADB.
                    </p>
                </div>
                <Link className="button primary" to="/management">
                    Register device
                </Link>
            </div>
            <div className="summary-grid">
                {["total", "online", "offline", "degraded"].map((group) => (
                    <div className="panel summary" key={group}>
                        <span>{group} devices</span>
                        <strong>
                            {devices.data
                                ? group === "total"
                                    ? devices.data.length
                                    : devices.data.filter(
                                          (d) => fleetGroup(d) === group,
                                      ).length
                                : "—"}
                        </strong>
                        <i className={`status-dot ${group}`} />
                    </div>
                ))}
            </div>
            <div className="toolbar panel">
                <label className="search">
                    Search devices
                    <input
                        placeholder="Name, model or IP address"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
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
                        <option value="degraded">Degraded</option>
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
            {devices.isPending ? (
                <div className="device-grid" aria-label="Loading devices">
                    {[1, 2, 3].map((n) => (
                        <div className="panel skeleton" key={n} />
                    ))}
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
                        <DeviceCard device={device} key={device.id} />
                    ))}
                </div>
            ) : (
                <div className="panel empty">
                    <Smartphone size={36} />
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
                </div>
            )}
        </>
    );
}
