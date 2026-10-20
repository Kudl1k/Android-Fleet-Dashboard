import { useMemo } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMetric, type HistoryPoint } from "../../lib/api";

const colors = ["#2563eb", "#dc2626", "#059669", "#9333ea", "#d97706", "#0891b2", "#db2777", "#64748b"];
export const deviceCharts = [
    ["cpu_usage", "CPU usage overall", "ratio"],
    ["cpu_core_usage", "CPU usage per core", "ratio"],
    ["memory_used", "RAM used", "bytes"],
    ["thermal_temperature", "All accessible temperatures", "celsius"],
    ["battery_temperature", "Battery temperature", "celsius"],
    ["gpu_usage", "GPU utilization", "ratio"],
    ["gpu_frequency", "GPU frequency", "hertz"],
    ["npu_frequency", "NPU frequency", "hertz"],
] as const;

export function metricSeries(points: HistoryPoint[]) {
    const identities = new Map<string, { key: string; label: string }>();
    const rows = new Map<number, Record<string, number | null>>();
    const ordered = [...points].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
    for (const point of ordered) {
        const labels = Object.entries(point.labels).sort(([a], [b]) => a.localeCompare(b));
        const identity = JSON.stringify([point.name, labels]);
        if (!identities.has(identity)) identities.set(identity, {
            key: `s${identities.size}`,
            label: labels.length ? labels.map(([key, value]) => `${key}: ${value}`).join(" · ") : point.name.replaceAll("_", " "),
        });
    }
    for (const point of ordered) {
        const labels = Object.entries(point.labels).sort(([a], [b]) => a.localeCompare(b));
        const series = identities.get(JSON.stringify([point.name, labels]))!;
        const time = Date.parse(point.observed_at);
        if (!rows.has(time)) rows.set(time, Object.fromEntries([
            ["time", time], ...Array.from(identities.values(), ({ key }) => [key, null]),
        ]));
        rows.get(time)![series.key] = point.unit === "ratio" ? point.value * 100 : point.value;
    }
    const data: Record<string, number | null>[] = [];
    let previous: number | undefined;
    for (const [time, row] of rows) {
        if (previous !== undefined && time - previous > 120000) data.push(Object.fromEntries([
            ["time", previous + 1], ...Array.from(identities.values(), ({ key }) => [key, null]),
        ]));
        data.push(row);
        previous = time;
    }
    return { series: [...identities.values()], data };
}

export default function MetricChart({ title, unit, points, loading, error }: {
    title: string; unit: string; points: HistoryPoint[]; loading?: boolean; error?: string;
}) {
    const { series, data } = useMemo(() => metricSeries(points), [points]);
    return <section className="panel chart-panel"><h3>{title}</h3>
        {loading ? <p role="status">Loading telemetry…</p> : error ? <p role="alert" className="error">{error}</p> : !points.length ? <p className="muted">Unavailable — no observations for this metric in this period.</p> : <>
            <div className="chart" role="img" aria-label={`${title} history, ${points.length} observations`}>
                <ResponsiveContainer width="100%" height="100%"><LineChart data={data}>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} minTickGap={45} tickFormatter={v => new Date(v).toLocaleTimeString()} />
                    <YAxis width={80} domain={unit === "ratio" ? [0, 100] : ["auto", "auto"]} tickFormatter={v => unit === "ratio" ? `${v}%` : formatMetric(Number(v), unit)} />
                    <Tooltip labelFormatter={v => new Date(Number(v)).toLocaleString()} formatter={v => unit === "ratio" ? `${Number(v).toFixed(1)}%` : formatMetric(Number(v), unit)} contentStyle={{ background: "var(--panel)", borderColor: "var(--border)" }} />
                    <Legend wrapperStyle={{ maxHeight: 70, overflowY: "auto" }} />
                    {series.map((item, i) => <Line key={item.key} dataKey={item.key} name={item.label} stroke={colors[i % colors.length]} dot={false} connectNulls={false} isAnimationActive={false} type="linear" />)}
                </LineChart></ResponsiveContainer>
            </div>
            <details><summary>View accessible observation table</summary><div className="table-wrap"><table>
                <thead><tr><th>Observed at</th><th>Core / sensor</th><th>{title}</th></tr></thead>
                <tbody>{points.slice(-100).map((point, i) => <tr key={i}><td>{new Date(point.observed_at).toLocaleString()}</td><td>{Object.entries(point.labels).map(([key, value]) => `${key}: ${value}`).join(" · ") || "Overall"}</td><td>{formatMetric(point.value, point.unit)}</td></tr>)}</tbody>
            </table></div><p className="muted">Most recent 100 observations.</p></details>
        </>}
    </section>;
}
