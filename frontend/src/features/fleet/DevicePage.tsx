import DeviceControl from "../control/DeviceControl";
import LiveScreen from "../screen/LiveScreen";
import TerminalPanel from "../terminal/TerminalPanel";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    CartesianGrid,
} from "recharts";
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
    const points = useMemo(
        () => chartPoints(history.data?.points ?? []),
        [history.data],
    );
    return (
        <section className="panel chart-panel">
            <h2>{label}</h2>
            {history.isPending ? (
                <div className="skeleton chart-skeleton" />
            ) : history.isError ? (
                <p className="error" role="alert">
                    {history.error.message}
                </p>
            ) : points.length ? (
                <>
                    <div
                        className="chart"
                        role="img"
                        aria-label={`${label} history, ${points.length} observations`}
                    >
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={points}>
                                <CartesianGrid
                                    stroke="var(--border)"
                                    strokeDasharray="3 3"
                                />
                                <XAxis
                                    dataKey="time"
                                    type="number"
                                    domain={["dataMin", "dataMax"]}
                                    tickFormatter={(v) =>
                                        new Date(v).toLocaleTimeString([], {
                                            hour: "2-digit",
                                            minute: "2-digit",
                                            ...(minutes >= 1440 ? { month: "short", day: "numeric" } as const : {}),
                                        })
                                    }
                                    minTickGap={45}
                                />
                                <YAxis
                                    tickFormatter={(v) =>
                                        unit === "bytes"
                                            ? formatMetric(Number(v), "bytes")
                                            : String(v)
                                    }
                                    width={70}
                                    unit={
                                        unit === "ratio"
                                            ? "%"
                                            : unit === "celsius"
                                              ? "°"
                                              : ""
                                    }
                                />
                                <Tooltip
                                    labelFormatter={(v) =>
                                        new Date(Number(v)).toLocaleString()
                                    }
                                    contentStyle={{
                                        background: "var(--panel)",
                                        borderColor: "var(--border)",
                                        borderRadius: 8,
                                    }}
                                />
                                <Line
                                    type="linear"
                                    dataKey="value"
                                    name={label}
                                    stroke="var(--accent)"
                                    strokeWidth={2}
                                    dot={false}
                                    connectNulls={false}
                                    isAnimationActive={false}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                    <details>
                        <summary>View accessible observation table</summary>
                        <div className="table-wrap">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Observed at</th>
                                        <th>{label}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {history.data?.points
                                        .slice(-100)
                                        .map((p, i) => (
                                            <tr key={i}>
                                                <td>
                                                    {new Date(
                                                        p.observed_at,
                                                    ).toLocaleString()}
                                                </td>
                                                <td>
                                                    {formatMetric(
                                                        p.value,
                                                        p.unit,
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                </tbody>
                            </table>
                        </div>
                        <p className="muted">Most recent 100 observations.</p>
                    </details>
                    {history.data?.truncated && (
                        <p className="muted">
                            Display limit reached; choose a shorter time range.
                        </p>
                    )}
                </>
            ) : (
                <p className="empty muted">
                    No supported observations in this time range.
                </p>
            )}
        </section>
    );
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
            <div className="detail-grid">
                {[
                    ["battery_level", "Battery level", "ratio"],
                    ["cpu_usage", "CPU utilization", "ratio"],
                    ["memory_used", "RAM used", "bytes"],
                    ["battery_temperature", "Battery temperature", "celsius"],
                ].map(([name, label, unit]) => (
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
