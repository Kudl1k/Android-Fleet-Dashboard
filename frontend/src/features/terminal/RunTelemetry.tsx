import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request, type History, type HistoryPoint } from "../../lib/api";
import MetricChart, { deviceCharts } from "../telemetry/MetricChart";

export interface DeviceRecording {
    enabled: boolean;
    interval_seconds: number;
    sample_count: number;
    last_error: string | null;
    available_metrics: string[];
}

export async function loadRunTelemetry(sessionId: string, signal?: AbortSignal) {
    const params = new URLSearchParams({ end: new Date().toISOString(), limit: "10000" });
    const points: HistoryPoint[] = [];
    let cursor: string | null = null;
    let pages = 0;
    do {
        if (cursor) params.set("cursor", cursor);
        const page = await request<History>(`/api/v1/terminal/sessions/${encodeURIComponent(sessionId)}/telemetry?${params}`, { signal });
        points.push(...page.points);
        cursor = page.next_cursor;
        pages++;
    } while (cursor && pages < 20);
    return { points, truncated: cursor !== null };
}

export default function RunTelemetry({ sessionId, deviceId, active, recording }: {
    sessionId: string; deviceId?: string; active: boolean; recording: DeviceRecording;
}) {
    const telemetry = useQuery({
        queryKey: ["run-telemetry", sessionId, active],
        queryFn: ({ signal }) => loadRunTelemetry(sessionId, signal),
        refetchInterval: active ? 15000 : false,
    });
    const points = telemetry.data?.points ?? [];
    return <section aria-label="Recorded device statistics"><h3>Recorded device statistics</h3>
        <p className="muted">Device-wide observations every {recording.interval_seconds} seconds while the run is active. These include all workloads on the Android device. Slow collection and disconnections leave gaps.</p>
        <p>{recording.sample_count} samples collected. GPU/NPU readings depend on driver access. NPU utilization is unavailable without a supported vendor counter; frequency does not indicate utilization.</p>
        {recording.last_error && <p role="alert">{recording.last_error}</p>}
        {deviceId && <Link to={`/devices/${encodeURIComponent(deviceId)}`}>Open device charts</Link>}
        <button disabled={!points.length} onClick={() => {
            const csv = ["observed_at,metric,value,unit,labels", ...points.map(point => [point.observed_at, point.name, String(point.value), point.unit, JSON.stringify(point.labels)].map(value => `"${value.replaceAll('"', '""')}"`).join(","))].join("\n");
            const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
            const link = document.createElement("a"); link.href = url; link.download = `device-statistics-${sessionId}.csv`; link.click(); URL.revokeObjectURL(url);
        }}>Download device statistics (CSV)</button>
        {telemetry.data?.truncated && <p role="alert">Display/export limit reached. The API provides further pages using its cursor.</p>}
        <div className="detail-grid">{deviceCharts.map(([name, title, unit]) => <MetricChart key={name} title={title} unit={unit} points={points.filter(point => point.name === name)} loading={telemetry.isPending} error={telemetry.isError ? telemetry.error.message : undefined} />)}</div>
    </section>;
}
