import Disclosure from "@/components/Disclosure";
import {
    Table,
    TableHeader,
    TableRow,
    TableHead,
    TableBody,
    TableCell,
} from "@/components/ui/table";

import ListRegion from "../../components/ListRegion";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ReferenceArea,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";
import { formatMetric, type HistoryPoint } from "../../lib/api";
import { decimate, groupThermal, type ChartRow } from "./series";

const colors = [
    "#3b82f6",
    "#ef4444",
    "#10b981",
    "#a855f7",
    "#f59e0b",
    "#06b6d4",
    "#ec4899",
    "#94a3b8",
];
export const deviceCharts = [
    ["cpu_usage", "CPU usage overall", "ratio"],
    ["cpu_core_usage", "CPU usage per core", "ratio"],
    ["memory_used", "RAM used", "bytes"],
    ["thermal_temperature", "Temperatures", "celsius"],
    ["battery_temperature", "Battery temperature", "celsius"],
    ["gpu_usage", "GPU utilization", "ratio"],
    ["gpu_frequency", "GPU frequency", "hertz"],
    ["npu_frequency", "NPU frequency", "hertz"],
] as const;

export function metricSeries(points: HistoryPoint[]) {
    const identities = new Map<string, { key: string; label: string }>();
    const rows = new Map<number, ChartRow>();
    const ordered = [...points].sort(
        (a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at),
    );
    for (const point of ordered) {
        const labels = Object.entries(point.labels).sort(([a], [b]) =>
            a.localeCompare(b),
        );
        const identity = JSON.stringify([point.name, labels]);
        if (!identities.has(identity))
            identities.set(identity, {
                key: `s${identities.size}`,
                label: labels.length
                    ? labels
                          .map(([key, value]) =>
                              key === "group" ? value : `${key}: ${value}`,
                          )
                          .join(" · ")
                    : point.name.replaceAll("_", " "),
            });
    }
    for (const point of ordered) {
        const labels = Object.entries(point.labels).sort(([a], [b]) =>
            a.localeCompare(b),
        );
        const series = identities.get(JSON.stringify([point.name, labels]))!;
        const time = Date.parse(point.observed_at);
        if (!rows.has(time))
            rows.set(
                time,
                Object.fromEntries([
                    ["time", time],
                    ...Array.from(identities.values(), ({ key }) => [
                        key,
                        null,
                    ]),
                ]),
            );
        rows.get(time)![series.key] =
            point.unit === "ratio" ? point.value * 100 : point.value;
    }
    const data: ChartRow[] = [];
    let previous: number | undefined;
    for (const [time, row] of rows) {
        if (previous !== undefined && time - previous > 120000)
            data.push(
                Object.fromEntries([
                    ["time", previous + 1],
                    ...Array.from(identities.values(), ({ key }) => [
                        key,
                        null,
                    ]),
                ]),
            );
        data.push(row);
        previous = time;
    }
    return { series: [...identities.values()], data };
}

export function formatElapsed(milliseconds: number) {
    const total = Math.max(0, Math.round(milliseconds / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = String(total % 60).padStart(2, "0");
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
}

/** Mounts chart drawing only once the panel scrolls near the viewport. */
function WhenVisible({ children }: { children: ReactNode }) {
    const ref = useRef<HTMLDivElement>(null);
    const [visible, setVisible] = useState(
        () => typeof IntersectionObserver === "undefined",
    );
    useEffect(() => {
        if (visible || !ref.current) return;
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting))
                    setVisible(true);
            },
            { rootMargin: "300px" },
        );
        observer.observe(ref.current);
        return () => observer.disconnect();
    }, [visible]);
    return (
        <div ref={ref} className="chart">
            {visible ? children : null}
        </div>
    );
}

/** Contiguous spans where a series is below `threshold`, for shading throttled periods. */
export function spansBelow(data: ChartRow[], key: string, threshold: number) {
    const spans: [number, number][] = [];
    let start: number | null = null;
    let last: number | null = null;
    for (const row of data) {
        const value = row[key];
        const time = row.time as number;
        if (value !== null && value < threshold) {
            if (start === null) start = time;
            last = time;
        } else if (start !== null) {
            spans.push([start, last ?? start]);
            start = null;
        }
    }
    if (start !== null) spans.push([start, last ?? start]);
    return spans;
}

export default function MetricChart({
    title,
    unit,
    points,
    loading,
    error,
    description,
    highlightBelow,
    elapsed = false,
}: {
    title: string;
    unit: string;
    points: HistoryPoint[];
    loading?: boolean;
    error?: string;
    description?: string;
    /** Shade periods where the first series drops below this value (in chart units). */
    highlightBelow?: number;
    /** Points are timed relative to a run start; show elapsed time instead of clock time. */
    elapsed?: boolean;
}) {
    const thermal = points.some((point) => point.name === "thermal_temperature");
    const [detailed, setDetailed] = useState(false);
    const [hidden, setHidden] = useState<Set<string>>(() => new Set());
    const shown = useMemo(
        () => (thermal && !detailed ? groupThermal(points) : points),
        [points, thermal, detailed],
    );
    const { series, data } = useMemo(() => {
        const chart = metricSeries(shown);
        return {
            series: chart.series,
            data: decimate(
                chart.data,
                chart.series.map((item) => item.key),
            ),
        };
    }, [shown]);
    const shaded = useMemo(
        () =>
            highlightBelow !== undefined && series[0]
                ? spansBelow(data, series[0].key, highlightBelow)
                : [],
        [data, series, highlightBelow],
    );
    const format = (value: unknown) =>
        unit === "ratio"
            ? `${Number(value).toFixed(1)}%`
            : formatMetric(Number(value), unit);
    return (
        <section className="panel chart-panel">
            <div className="chart-heading">
                <h3>{title}</h3>
                {thermal && points.length > 0 && (
                    <label className="chart-toggle">
                        <input
                            type="checkbox"
                            checked={detailed}
                            onChange={(event) => {
                                setDetailed(event.target.checked);
                                setHidden(new Set());
                            }}
                        />
                        Individual sensors
                    </label>
                )}
            </div>
            {description && (
                <p className="muted chart-description">{description}</p>
            )}
            {loading ? (
                <p role="status">Loading telemetry…</p>
            ) : error ? (
                <p role="alert" className="error">
                    {error}
                </p>
            ) : !points.length ? (
                <p className="muted">
                    Unavailable — no observations for this metric in this
                    period.
                </p>
            ) : (
                <>
                    <div
                        role="img"
                        aria-label={`${title} history, ${points.length} observations${thermal && !detailed ? ", hottest sensor per type" : ""}`}
                    >
                        <WhenVisible>
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart
                                    data={data}
                                    syncId={elapsed ? "run-compare" : "device-history"}
                                    syncMethod="value"
                                >
                                    <CartesianGrid
                                        stroke="var(--border)"
                                        strokeDasharray="3 3"
                                    />
                                    <XAxis
                                        dataKey="time"
                                        type="number"
                                        scale="time"
                                        domain={["dataMin", "dataMax"]}
                                        minTickGap={45}
                                        stroke="var(--muted)"
                                        tickFormatter={(v) =>
                                            elapsed
                                                ? formatElapsed(Number(v))
                                                : new Date(v).toLocaleTimeString([], {
                                                      hour: "2-digit",
                                                      minute: "2-digit",
                                                  })
                                        }
                                    />
                                    <YAxis
                                        width={72}
                                        stroke="var(--muted)"
                                        domain={
                                            unit === "ratio"
                                                ? [0, 100]
                                                : ["auto", "auto"]
                                        }
                                        tickFormatter={(v) =>
                                            unit === "ratio"
                                                ? `${v}%`
                                                : unit === "bytes" && Number(v) >= 2 ** 30
                                                  ? // Narrow RAM ranges need two decimals to keep ticks distinct.
                                                    `${(Number(v) / 2 ** 30).toFixed(2)} GiB`
                                                  : formatMetric(Number(v), unit)
                                        }
                                    />
                                    {shaded.map(([from, to]) => (
                                        <ReferenceArea
                                            key={from}
                                            x1={from}
                                            x2={to}
                                            fill="var(--yellow)"
                                            fillOpacity={0.16}
                                            ifOverflow="hidden"
                                        />
                                    ))}
                                    <Tooltip
                                        labelFormatter={(v) =>
                                            elapsed
                                                ? `+${formatElapsed(Number(v))}`
                                                : new Date(Number(v)).toLocaleString()
                                        }
                                        formatter={format}
                                        itemSorter={(item) =>
                                            -Number(item.value ?? 0)
                                        }
                                        contentStyle={{
                                            background: "var(--panel-raised)",
                                            borderColor: "var(--border)",
                                            borderRadius: 8,
                                            fontSize: 12,
                                        }}
                                    />
                                    {series.length > 1 && (
                                        <Legend
                                            onClick={(entry) => {
                                                const key = String(
                                                    entry.dataKey,
                                                );
                                                setHidden((old) => {
                                                    const next = new Set(old);
                                                    if (!next.delete(key))
                                                        next.add(key);
                                                    return next;
                                                });
                                            }}
                                            formatter={(label, entry) => (
                                                <span
                                                    className="chart-legend-item"
                                                    data-hidden={
                                                        hidden.has(
                                                            String(
                                                                entry.dataKey,
                                                            ),
                                                        ) || undefined
                                                    }
                                                >
                                                    {label}
                                                </span>
                                            )}
                                            wrapperStyle={{
                                                maxHeight: 70,
                                                overflowY: "auto",
                                                cursor: "pointer",
                                            }}
                                        />
                                    )}
                                    {series.map((item, i) => (
                                        <Line
                                            key={item.key}
                                            dataKey={item.key}
                                            name={item.label}
                                            hide={hidden.has(item.key)}
                                            stroke={colors[i % colors.length]}
                                            strokeWidth={1.6}
                                            dot={false}
                                            activeDot={{ r: 3 }}
                                            connectNulls={false}
                                            isAnimationActive={false}
                                            type="linear"
                                        />
                                    ))}
                                </LineChart>
                            </ResponsiveContainer>
                        </WhenVisible>
                    </div>
                    <Disclosure title={"View accessible observation table"}>
                        <ListRegion
                            label={`${title} observations`}
                            className="observation-table"
                        >
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead scope="col">
                                            Observed at
                                        </TableHead>
                                        <TableHead scope="col">
                                            Core / sensor
                                        </TableHead>
                                        <TableHead
                                            scope="col"
                                            className="numeric-cell"
                                        >
                                            {title}
                                        </TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {points.slice(-100).map((point, i) => (
                                        <TableRow key={i}>
                                            <TableCell>
                                                {new Date(
                                                    point.observed_at,
                                                ).toLocaleString()}
                                            </TableCell>
                                            <TableCell>
                                                {Object.entries(point.labels)
                                                    .map(
                                                        ([key, value]) =>
                                                            `${key}: ${value}`,
                                                    )
                                                    .join(" · ") || "Overall"}
                                            </TableCell>
                                            <TableCell className="numeric-cell">
                                                {formatMetric(
                                                    point.value,
                                                    point.unit,
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </ListRegion>
                        <p className="muted">
                            Showing {Math.min(points.length, 100)} of{" "}
                            {points.length} observations (most recent 100).
                        </p>
                    </Disclosure>
                </>
            )}
        </section>
    );
}
