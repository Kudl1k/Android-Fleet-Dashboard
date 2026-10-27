import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Download, FlaskConical, GitCompareArrows, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import StatusChip from "../../components/StatusChip";
import ListRegion from "../../components/ListRegion";
import { formatMetric, request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useDevices } from "../../lib/hooks";
import MetricChart, { formatElapsed } from "../telemetry/MetricChart";
import { loadRunTelemetry, type DeviceRecording } from "../terminal/RunTelemetry";
import { alignRun, hottestOverall, summarizeRun, type RunSummary } from "./runSummary";

interface Run {
    id: string;
    device_id: string | null;
    command: string | null;
    owner: string;
    created_at: number;
    ended_at: number | null;
    duration: number;
    state: string;
    device_recording?: DeviceRecording;
}

const compareMetrics: { name: string; title: string; unit: string; hottest?: boolean }[] = [
    { name: "cpu_usage", title: "CPU usage", unit: "ratio" },
    { name: "memory_used", title: "RAM used", unit: "bytes" },
    { name: "thermal_temperature", title: "Hottest sensor", unit: "celsius", hottest: true },
    { name: "battery_level", title: "Battery level", unit: "ratio" },
];

function percent(value: number | null) {
    return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function summaryCells(summary: RunSummary | undefined) {
    if (!summary) return ["…", "…", "…", "…", "…"];
    return [
        `${percent(summary.cpuAverage)} / ${percent(summary.cpuPeak)}`,
        summary.memoryPeak === null ? "—" : formatMetric(summary.memoryPeak, "bytes"),
        summary.hottest === null ? "—" : formatMetric(summary.hottest, "celsius"),
        summary.lowestCeiling === null
            ? "Not observed"
            : summary.lowestCeiling < 0.995
              ? `Yes, down to ${percent(summary.lowestCeiling)}`
              : "No",
        summary.batteryDrop === null ? "—" : `${(summary.batteryDrop * 100).toFixed(1)} pp`,
    ];
}

export default function RunsPage() {
    const auth = useAuth();
    const devices = useDevices();
    const allowed = auth.can("terminal:view");
    const [device, setDevice] = useState("");
    const [compare, setCompare] = useState<string[]>([]);
    const sessions = useQuery({
        queryKey: ["runs"],
        queryFn: ({ signal }) => request<{ items: Run[] }>("/api/v1/terminal/sessions", { signal }),
        refetchInterval: 15000,
        enabled: allowed,
    });
    const runs = useMemo(
        () =>
            (sessions.data?.items ?? [])
                .filter((run) => run.command && (!device || run.device_id === device))
                .sort((a, b) => b.created_at - a.created_at),
        [sessions.data, device],
    );
    const recorded = runs.filter((run) => run.device_recording?.enabled);
    const telemetry = useQueries({
        queries: recorded.map((run) => ({
            queryKey: ["run-telemetry", run.id, run.state === "active"],
            queryFn: ({ signal }: { signal: AbortSignal }) => loadRunTelemetry(run.id, signal),
            refetchInterval: run.state === "active" ? 15000 : (false as const),
            staleTime: run.state === "active" ? 0 : Infinity,
            enabled: auth.can("telemetry.read"),
        })),
    });
    const points = new Map(recorded.map((run, index) => [run.id, telemetry[index]?.data?.points]));
    const summaries = new Map(
        recorded.map((run) => {
            const data = points.get(run.id);
            return [run.id, data ? summarizeRun(data) : undefined] as const;
        }),
    );
    const name = (id: string | null) =>
        devices.data?.find((item) => item.id === id)?.name ?? id ?? "SSH host";
    const compared = compare
        .map((id) => recorded.find((run) => run.id === id))
        .filter((run): run is Run => Boolean(run));
    const runLabel = (run: Run, index: number) =>
        `${String.fromCharCode(65 + index)}: ${name(run.device_id)}`;
    function toggleCompare(id: string) {
        setCompare((old) =>
            old.includes(id) ? old.filter((item) => item !== id) : [...old.slice(-1), id],
        );
    }
    function exportCsv() {
        const header = ["started", "device", "command", "state", "duration_s", "samples", "cpu_avg", "cpu_peak", "ram_peak_bytes", "hottest_c", "lowest_ceiling", "battery_drop"];
        const lines = recorded.map((run) => {
            const s = summaries.get(run.id);
            return [
                new Date(run.created_at * 1000).toISOString(),
                name(run.device_id),
                run.command ?? "",
                run.state,
                run.duration.toFixed(0),
                s?.samples ?? "",
                s?.cpuAverage ?? "",
                s?.cpuPeak ?? "",
                s?.memoryPeak ?? "",
                s?.hottest ?? "",
                s?.lowestCeiling ?? "",
                s?.batteryDrop ?? "",
            ]
                .map((cell) => `"${String(cell).replaceAll('"', '""')}"`)
                .join(",");
        });
        const url = URL.createObjectURL(new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = "program-runs.csv";
        link.click();
        URL.revokeObjectURL(url);
    }
    if (!allowed)
        return (
            <>
                <h1>Program runs</h1>
                <p className="panel">Terminal access is required to view program runs.</p>
            </>
        );
    return (
        <>
            <div className="page-heading">
                <div>
                    <h1>Program runs</h1>
                    <p className="muted">
                        Programs started from the terminal, with device statistics recorded while they ran.
                    </p>
                </div>
                <Button variant="outline" disabled={!recorded.length} onClick={exportCsv}>
                    <Download data-icon="inline-start" aria-hidden="true" />
                    Export summary (CSV)
                </Button>
            </div>
            <section className="panel">
                <div className="runs-toolbar">
                    <label>
                        Device
                        <select value={device} onChange={(event) => setDevice(event.target.value)}>
                            <option value="">All devices</option>
                            {devices.data?.map((item) => (
                                <option key={item.id} value={item.id}>
                                    {item.name}
                                </option>
                            ))}
                        </select>
                    </label>
                    <p className="muted" role="status">
                        {sessions.data ? `${runs.length} runs, ${recorded.length} with recorded statistics` : "Loading runs…"}
                        {compare.length > 0 && ` · ${compare.length} of 2 selected for comparison`}
                    </p>
                </div>
                {sessions.isError && <p role="alert" className="error">{sessions.error.message}</p>}
                {sessions.isSuccess && !runs.length && (
                    <div className="empty">
                        <FlaskConical size={32} aria-hidden="true" />
                        <h2>No program runs yet</h2>
                        <p className="muted">
                            Open a device, go to Device tools → Terminal, and run a program with
                            “Record device statistics” enabled.
                        </p>
                    </div>
                )}
                {runs.length > 0 && (
                    <ListRegion label="Program runs">
                        <table className="runs-table">
                            <thead>
                                <tr>
                                    <th scope="col">Compare</th>
                                    <th scope="col">Run</th>
                                    <th scope="col">State</th>
                                    <th scope="col" className="numeric-cell">Duration</th>
                                    <th scope="col">CPU avg / peak</th>
                                    <th scope="col">RAM peak</th>
                                    <th scope="col">Hottest</th>
                                    <th scope="col">Throttled</th>
                                    <th scope="col">Battery used</th>
                                </tr>
                            </thead>
                            <tbody>
                                {runs.map((run) => {
                                    const isRecorded = Boolean(run.device_recording?.enabled);
                                    return (
                                        <tr key={run.id} data-selected={compare.includes(run.id) || undefined}>
                                            <td>
                                                <input
                                                    type="checkbox"
                                                    className="run-compare"
                                                    aria-label={`Compare run started ${new Date(run.created_at * 1000).toLocaleString()}`}
                                                    disabled={!isRecorded}
                                                    checked={compare.includes(run.id)}
                                                    onChange={() => toggleCompare(run.id)}
                                                />
                                            </td>
                                            <td>
                                                <strong>
                                                    {run.device_id ? (
                                                        <Link to={`/devices/${encodeURIComponent(run.device_id)}`}>{name(run.device_id)}</Link>
                                                    ) : (
                                                        name(run.device_id)
                                                    )}
                                                </strong>
                                                <code className="run-command" title={run.command ?? ""}>{run.command}</code>
                                                <span className="muted">
                                                    {new Date(run.created_at * 1000).toLocaleString()} · {run.owner}
                                                </span>
                                            </td>
                                            <td><StatusChip value={run.state} /></td>
                                            <td className="numeric-cell">{formatElapsed(run.duration * 1000)}</td>
                                            {isRecorded ? (
                                                summaryCells(summaries.get(run.id)).map((cell, index) => (
                                                    <td key={index}>{cell}</td>
                                                ))
                                            ) : (
                                                <td colSpan={5} className="muted">
                                                    Statistics were not recorded for this run
                                                </td>
                                            )}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </ListRegion>
                )}
            </section>
            {compared.length === 2 && (
                <section className="panel run-comparison" aria-label="Run comparison">
                    <div className="results-heading">
                        <h2>
                            <GitCompareArrows size={18} aria-hidden="true" /> Comparison
                        </h2>
                        <Button variant="ghost" onClick={() => setCompare([])}>
                            <X data-icon="inline-start" aria-hidden="true" />
                            Clear
                        </Button>
                    </div>
                    <p className="muted">Both runs are aligned to their start, so the horizontal axis is elapsed time.</p>
                    <dl className="compare-legend">
                        {compared.map((run, index) => (
                            <div key={run.id}>
                                <dt>{runLabel(run, index)}</dt>
                                <dd><code>{run.command}</code></dd>
                            </div>
                        ))}
                    </dl>
                    <div className="detail-grid">
                        {compareMetrics.map((metric) => (
                            <MetricChart
                                key={metric.name}
                                title={metric.title}
                                unit={metric.unit}
                                elapsed
                                points={compared.flatMap((run, index) =>
                                    alignRun(
                                        points.get(run.id) ?? [],
                                        metric.name,
                                        run.created_at,
                                        runLabel(run, index),
                                        metric.hottest ? hottestOverall : undefined,
                                    ),
                                )}
                            />
                        ))}
                    </div>
                </section>
            )}
        </>
    );
}
