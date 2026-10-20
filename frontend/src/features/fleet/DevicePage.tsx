import AdbTcpSwitch from "../management/AdbTcpSwitch";
import DeviceSetup from "../control/DeviceSetup";
import DeviceControl from "../control/DeviceControl";
import LiveScreen from "../screen/LiveScreen";
import TerminalPanel from "../terminal/TerminalPanel";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import MetricChart, { deviceCharts } from "../telemetry/MetricChart";
import DeviceRunCharts from "../terminal/DeviceRunCharts";
import { useDevice, useMetrics, useHistory } from "../../lib/hooks";
import { formatMetric, metricValue, type HistoryPoint } from "../../lib/api";
import { fleetGroup } from "./FleetPage";
export function chartPoints(points: HistoryPoint[]) {
    const result: { time: number; value: number | null }[] = [];
    let previous: number | null = null;
    for (const p of points) {
        const time = Date.parse(p.observed_at);
        if (previous !== null && time - previous > 120000)
            result.push({ time: previous + 1, value: null });
        result.push({
            time,
            value: p.unit === "ratio" ? p.value * 100 : p.value,
        });
        previous = time;
    }
    return result;
}
function HistoryChart({
    id,
    minutes,
    name,
    label,
    unit,
}: {
    id: string;
    minutes: number;
    name: string;
    label: string;
    unit: string;
}) {
    const history = useHistory(id, minutes, name);
    return <>
        <MetricChart title={label} unit={unit} points={history.data?.points ?? []} loading={history.isPending} error={history.isError ? history.error.message : undefined} />
        {history.data?.truncated && <p className="muted">Display limit reached; choose a shorter time range.</p>}
    </>;
}

export default function DevicePage() {
    const { id = "" } = useParams();
    const device = useDevice(id);
    const metrics = useMetrics(id);
    const [minutes, setMinutes] = useState(60);
    if (device.isPending)
        return <div className="panel skeleton" aria-label="Loading device" />;
    if (device.isError)
        return (
            <div className="panel error" role="alert">
                {device.error.message}
                <p>
                    <Link to="/">Return to fleet</Link>
                </p>
            </div>
        );
    const d = device.data;
    const current = d.state === "online" && !metrics.isError ? metrics.data : undefined;
    const values = current && !current.stale ? current.values : [];
    const used = metricValue(current, "memory_used");
    const total = metricValue(current, "memory_total");
    const storageUsed = metricValue(current, "storage_used");
    const storageTotal = metricValue(current, "storage_total");
    return (
        <>
            <Link className="muted back" to="/">
                ← Fleet overview
            </Link>
            <div className="page-heading">
                <div>
                    <p className="eyebrow">DEVICE DETAIL</p>
                    <h1>
                        {d.name}{" "}
                        <span
                            className={`badge ${fleetGroup(d)}`}
                        >
                            {d.state.replaceAll("_", " ")}
                        </span>
                    </h1>
                    <p className="muted">
                        {d.manufacturer ?? "Unknown manufacturer"} ·{" "}
                        {d.model ?? "Unknown model"} · Android{" "}
                        {d.android_version ?? "unknown"}
                    </p>
                </div>
                <Link
                    className="button"
                    to={`/management?device=${encodeURIComponent(id)}`}
                >
                    Manage device
                </Link>
            </div>
            {d.connection_type === "wireless_adb" && <AdbTcpSwitch id={id} online={d.state === "online"} />}
            <div className="panel freshness">
                <span
                    className={`status-dot ${d.state === "online" && !metrics.isError && metrics.data?.observed_at && !metrics.data.stale ? "online" : "degraded"}`}
                />
                <span>
                    {metrics.isPending
                        ? "Loading current telemetry…"
                        : metrics.isError
                        ? metrics.error.message
                        : metrics.data?.stale
                          ? "Telemetry stale; latest values withheld"
                          : d.state !== "online"
                            ? "Device disconnected; latest values unavailable"
                            : metrics.data?.observed_at
                              ? "Latest collection " +
                                new Date(
                                    metrics.data.observed_at,
                                ).toLocaleString()
                              : "Waiting for a successful collection"}
                </span>
                <span className="muted">
                    {metrics.data?.observed_at && (
                        <>Last successful collection {new Date(metrics.data.observed_at).toLocaleString()} · </>
                    )}
                    Last seen{" "}
                    {d.last_seen
                        ? new Date(d.last_seen).toLocaleString()
                        : "never"}
                </span>
            </div>
            {d.error_message && (
                <div className="panel error">
                    <strong>{d.error_code}</strong>
                    <p>{d.error_message}</p>
                </div>
            )}
            <div className="detail-grid">
                <section className="panel">
                    <h2>Current telemetry</h2>
                    {metrics.isPending && <div className="skeleton chart-skeleton" aria-label="Loading telemetry" />}
                    {metrics.isError && <button onClick={() => void metrics.refetch()}>Retry telemetry</button>}
                    <dl className="metric-list">
                        <div>
                            <dt>RAM utilization</dt>
                            <dd>
                                {formatMetric(
                                    used !== null && total !== null && total > 0
                                        ? used / total
                                        : null,
                                    "ratio",
                                )}
                            </dd>
                        </div>
                        <div>
                            <dt>Storage utilization</dt>
                            <dd>
                                {formatMetric(
                                    storageUsed !== null &&
                                        storageTotal !== null &&
                                        storageTotal > 0
                                        ? storageUsed / storageTotal
                                        : null,
                                    "ratio",
                                )}
                            </dd>
                        </div>
                        {[
                            "battery_level",
                            "battery_charging",
                            "battery_status",
                            "battery_health",
                            "battery_temperature",
                            "battery_voltage",
                            "cpu_usage",
                            "cpu_core_usage",
                            "gpu_usage",
                            "gpu_frequency",
                            "npu_frequency",
                            "cpu_frequency",
                            "memory_used",
                            "memory_available",
                            "memory_total",
                            "storage_used",
                            "storage_free",
                            "storage_total",
                            "network_receive",
                            "network_transmit",
                            "uptime",
                            "thermal_temperature",
                            "thermal_status",
                        ].map((name) => {
                            const matches = values.filter(
                                (v) => v.name === name,
                            );
                            return matches.length ? (
                                matches.map((m, i) => (
                                    <div key={`${name}-${i}`}>
                                        <dt>
                                            {name.replaceAll("_", " ")}{" "}
                                            {Object.values(m.labels).length >
                                                0 && (
                                                <small>
                                                    (
                                                    {Object.values(
                                                        m.labels,
                                                    ).join(", ")}
                                                    )
                                                </small>
                                            )}
                                        </dt>
                                        <dd>
                                            {name === "battery_charging"
                                                ? m.value === 1
                                                    ? "Charging"
                                                    : "Not charging"
                                                : name === "battery_status"
                                                  ? ({
                                                        1: "Unknown",
                                                        2: "Charging",
                                                        3: "Discharging",
                                                        4: "Not charging",
                                                        5: "Full",
                                                    }[m.value] ?? "Unknown")
                                                  : name === "battery_health"
                                                    ? ({
                                                          1: "Unknown",
                                                          2: "Good",
                                                          3: "Overheat",
                                                          4: "Dead",
                                                          5: "Over voltage",
                                                          6: "Failure",
                                                          7: "Cold",
                                                      }[m.value] ?? "Unknown")
                                                    : formatMetric(
                                                          m.value,
                                                          m.unit,
                                                      )}
                                        </dd>
                                    </div>
                                ))
                            ) : (
                                <div key={name}>
                                    <dt>{name.replaceAll("_", " ")}</dt>
                                    <dd className="muted">Unavailable</dd>
                                </div>
                            );
                        })}
                    </dl>
                    <p className="muted">
                        Network values are cumulative interface counters.
                        Unsupported sources remain unavailable.
                    </p>
                </section>
                <section className="panel">
                    <h2>Identity & capabilities</h2>
                    <dl className="metric-list">
                        <div>
                            <dt>Root access</dt>
                            <dd>
                                {d.root_available === null
                                    ? "Unknown"
                                    : d.root_available
                                      ? "Available"
                                      : "Unavailable"}
                            </dd>
                        </div>
                        <div>
                            <dt>Connection</dt>
                            <dd>{d.connection_type.replaceAll("_", " ")}</dd>
                        </div>
                        <div>
                            <dt>Endpoint</dt>
                            <dd>
                                {d.host
                                    ? `${d.host}:${d.port ?? "—"}`
                                    : d.serial}
                            </dd>
                        </div>
                        <div>
                            <dt>Automatic reconnect</dt>
                            <dd>{d.auto_connect ? "Enabled" : "Disabled"}</dd>
                        </div>
                        <div>
                            <dt>Device ID</dt>
                            <dd className="mono">{d.id}</dd>
                        </div>
                    </dl>
                    <h3>Observed capabilities</h3>
                    <div className="capabilities">
                        {d.capabilities.length ? (
                            d.capabilities.map((c) => (
                                <span className="badge" key={c}>
                                    {c.replaceAll("_", " ")}
                                </span>
                            ))
                        ) : (
                            <p className="muted">
                                No current capability observations.
                            </p>
                        )}
                    </div>
                </section>
            </div>
            <DeviceSetup id={id} online={d.state === "online"} />
            <DeviceControl id={id} online={d.state === "online"} />
            <LiveScreen key={id} id={id} online={d.state === "online"} />
            <TerminalPanel key={`terminal-${id}`} deviceId={id} online={d.state === "online"} />
            <div className="page-heading">
                <div>
                    <h2>Historical telemetry</h2>
                    <p className="muted">
                        Persisted observations. Gaps longer than two minutes
                        break the line. Unavailable sources are not replaced
                        with zero.
                    </p>
                </div>
                <label>
                    Time range
                    <select
                        value={minutes}
                        onChange={(e) => setMinutes(Number(e.target.value))}
                    >
                        {[
                            [15, "15 minutes"],
                            [60, "1 hour"],
                            [360, "6 hours"],
                            [1440, "24 hours"],
                            [10080, "7 days"],
                        ].map(([v, label]) => (
                            <option value={v} key={v}>
                                {label}
                            </option>
                        ))}
                    </select>
                </label>
            </div>
            <DeviceRunCharts deviceId={id} />
            <div className="detail-grid">
                {[["battery_level", "Battery level", "ratio"], ...deviceCharts].map(([name, label, unit]) => (
                    <HistoryChart
                        key={name}
                        id={id}
                        minutes={minutes}
                        name={name}
                        label={label}
                        unit={unit}
                    />
                ))}
            </div>
        </>
    );
}
