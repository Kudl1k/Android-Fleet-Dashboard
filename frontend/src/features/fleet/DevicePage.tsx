import ListRegion from "../../components/ListRegion";
import AdbTcpSwitch from "../management/AdbTcpSwitch";
import DeviceSetup from "../control/DeviceSetup";
import DeviceControl from "../control/DeviceControl";
import LiveScreen from "../screen/LiveScreen";
import TerminalPanel from "../terminal/TerminalPanel";
import { useContext, useState, type ReactNode } from "react";
import { ArrowLeft, Settings, RefreshCw, Monitor, Terminal, SlidersHorizontal, Wrench, ChartNoAxesCombined } from "lucide-react";
import DeviceTelemetry from "./DeviceTelemetry";
import { Link, useParams } from "react-router-dom";
import MetricChart, { deviceCharts } from "../telemetry/MetricChart";
import DeviceRunCharts from "../terminal/DeviceRunCharts";
import { PollContext, useDevice, useMetrics, useHistory } from "../../lib/hooks";
import { type HistoryPoint } from "../../lib/api";
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
    // Reset workspace drafts and disclosure state when navigating directly between devices.
    return <DeviceWorkspace key={id} id={id} />;
}
function DeviceWorkspace({ id }: { id: string }) {
    const device = useDevice(id);
    const metrics = useMetrics(id);
    const polling = useContext(PollContext);
    const [historyOpened, setHistoryOpened] = useState(false);
    const [screenState, setScreenState] = useState("stopped");
    if (device.isPending) return <div className="panel skeleton" role="status" aria-label="Loading device" />;
    if (!device.data) return <div className="panel error" role="alert"><h1>Could not load device</h1><p>{device.error?.message}</p><div className="actions"><button onClick={() => void device.refetch()}>Retry device</button><Link to="/">Return to fleet</Link></div></div>;
    const d = device.data;
    const online = d.state === "online" && !device.isError;
    const current = online && !metrics.isError && metrics.data?.state === "online" && !metrics.data.stale && metrics.data.observed_at ? metrics.data : undefined;
    const [freshness, explanation] = (() => {
        if (device.isError) return ["Connection check failed", "Connection could not be verified. Values are withheld until a successful check."];
        if (!online) return ["Device disconnected", "Current values are withheld. Historical telemetry remains available."];
        if (metrics.isPending) return ["Loading telemetry…", "Requesting the latest collection from the manager."];
        if (metrics.isError) return ["Telemetry request failed", metrics.error.message];
        if (metrics.data?.stale) return ["Telemetry stale", "Latest values are withheld until a fresh collection succeeds."];
        if (metrics.data?.state !== "online") return ["Telemetry connection not confirmed", "No current observations. Check device connectivity and collection status."];
        if (!metrics.data.observed_at) return ["Waiting for first collection", "No successful collection yet. Check device connectivity and collection status."];
        if (!current?.values.length) return ["No observations collected", "The collection returned no metric observations."];
        if (!polling) return ["Telemetry refresh paused", "Showing the last checked collection. Refresh to check for newer observations."];
        return ["Telemetry current", "Values reflect the latest successful collection."];
    })();
    const refreshing = device.isFetching || metrics.isFetching;
    return <div className="device-workspace">
        <Link className="muted back device-back" to="/"><ArrowLeft size={16} aria-hidden="true" />Fleet overview</Link>
        <header className="page-heading device-heading">
            <div><div className="device-title"><h1>{d.name}</h1><span className={`badge ${device.isError ? "degraded" : fleetGroup(d)}`}>{device.isError ? "Connection unknown" : d.state.replaceAll("_", " ")}</span></div>
                <p className="muted">{d.manufacturer ?? "Unknown manufacturer"} · {d.model ?? "Unknown model"} · Android {d.android_version ?? "unknown"}</p>
                <p className="device-endpoint"><span>{{wireless_adb: "Wireless ADB", tcp: "ADB TCP", usb: "USB"}[d.connection_type] ?? d.connection_type.replaceAll("_", " ")}</span><code>{d.host ? `${d.host}:${d.port ?? "—"}` : d.serial}</code></p>
            </div>
            <Link className="button primary" to={`/management?device=${encodeURIComponent(id)}`}><Settings size={17} aria-hidden="true" />Manage device</Link>
        </header>
        <section className="panel device-freshness" aria-label="Telemetry freshness">
            <div><div className="device-collection-state" role="status"><span aria-hidden="true" className={`status-dot ${current?.values.length && polling ? "online" : "degraded"}`} /><strong>{freshness}</strong></div><p className="muted">{explanation}</p>
                {metrics.data?.observed_at && <p className="muted">Last successful collection <time dateTime={metrics.data.observed_at}>{new Date(metrics.data.observed_at).toLocaleString()}</time></p>}
            </div>
            <button className="device-refresh" aria-busy={refreshing} disabled={refreshing} onClick={() => { void device.refetch(); void metrics.refetch(); }}><RefreshCw size={16} aria-hidden="true" />{refreshing ? "Refreshing…" : "Refresh status"}</button>
        </section>
        {device.isError && <p className="error" role="alert">{device.error.message}</p>}
        {d.error_message && <div className="panel error" role="alert"><strong>{d.error_code ?? "Device needs attention"}</strong><p>{d.error_message}</p><Link to={`/management?device=${encodeURIComponent(id)}`}>Review device connection</Link></div>}
        <nav className="device-shortcuts" aria-label="Device workspace"><a href="#device-monitoring">Monitoring</a><a href="#device-history" onClick={() => { const history = document.getElementById("device-history"); if (history instanceof HTMLDetailsElement) history.open = true; }}>History</a><a href="#device-tools">Device tools</a></nav>
        <section id="device-monitoring" aria-labelledby="current-telemetry-title" className="panel device-monitoring">
            <h2 id="current-telemetry-title">Current telemetry</h2>
            <DeviceTelemetry current={current} />
            {!current?.values.length && <div className="device-telemetry-empty" aria-busy={metrics.isPending}><p>{metrics.isPending ? "Loading observations…" : "No current values to display."}</p><p className="muted">{online ? "Use Refresh status to check again, or inspect historical telemetry below." : "Reconnect from device management to resume monitoring."}</p></div>}
        </section>
        <details className="panel device-disclosure device-identity"><summary><strong>Identity & capabilities</strong><span className="muted">Connection details and observed support</span></summary><div className="device-disclosure-body">
            <dl className="metric-list device-identity-list">
                <div><dt>Device ID</dt><dd className="mono">{d.id}</dd></div>
                <div><dt>Serial</dt><dd className="mono">{d.serial}</dd></div>
                <div><dt>Root access</dt><dd>{d.root_available === null ? "Unknown" : d.root_available ? "Available" : "Unavailable"}</dd></div>
                <div><dt>Automatic reconnect</dt><dd>{d.auto_connect ? "Enabled" : "Disabled"}</dd></div>
                <div><dt>Last seen</dt><dd>{d.last_seen ? new Date(d.last_seen).toLocaleString() : "Never"}</dd></div>
            </dl><div className="device-list-heading"><h3>Observed capabilities</h3><span className="muted">{d.capabilities.length} observed</span></div>{d.capabilities.length ? <ListRegion label="Observed capabilities"><ul className="capabilities device-capability-list">{d.capabilities.map(capability => <li key={capability}><span className="badge">{capability.replaceAll("_", " ")}</span></li>)}</ul></ListRegion> : <p className="muted">No current capability observations.</p>}
        </div></details>
        <details id="device-history" className="panel device-disclosure" onToggle={event => { if (event.currentTarget.open) setHistoryOpened(true); }}><summary><ChartNoAxesCombined size={18} aria-hidden="true" /><strong>Historical telemetry</strong><span className="muted">Trends, time ranges and recorded runs</span></summary><div className="device-disclosure-body">{historyOpened && <DeviceHistory id={id} />}</div></details>
        <section id="device-tools" aria-labelledby="device-tools-title" className="device-tools">
            <h2 id="device-tools-title">Device tools</h2><p className="muted">Open a tool to inspect or interact. Sessions continue when collapsed; use Stop stream or Close session to end them.</p>
            <Tool title="Live screen" description={`${screenState} · View the display and request control`} icon={<Monitor size={18} aria-hidden="true" />}><LiveScreen id={id} online={online} onStateChange={setScreenState} /></Tool>
            <Tool title="Terminal" description="ADB shell, SSH and recorded program runs" icon={<Terminal size={18} aria-hidden="true" />}><TerminalPanel deviceId={id} online={online} /></Tool>
            <Tool title="Device controls" description="Power, screenshots, applications and operation results" icon={<SlidersHorizontal size={18} aria-hidden="true" />}><DeviceControl id={id} online={online} /></Tool>
            <Tool title="Setup & connectivity" description="Optional app setup and ADB connection tools" icon={<Wrench size={18} aria-hidden="true" />}><p className="muted">Available actions depend on your access. Optional app and SSH setup is separate from fleet monitoring over ADB.</p><DeviceSetup id={id} online={online} /><section className="device-connectivity"><div className="device-section-heading"><h3>ADB connection</h3><Link className="button" to={`/management?device=${encodeURIComponent(id)}`}>Connection settings</Link></div>{d.connection_type === "wireless_adb" && <AdbTcpSwitch id={id} online={online} />}</section></Tool>
        </section>
    </div>;
}
function Tool({ title, description, icon, children }: { title: string; description: string; icon: ReactNode; children: ReactNode }) {
    // Native disclosure hides the surface without unmounting it. Stream/session cleanup
    // stays owned by the tools; terminal ResizeObserver refits on reopening.
    return <details className="panel device-disclosure"><summary>{icon}<strong>{title}</strong><span className="muted">{description}</span></summary><div className="device-disclosure-body">{children}</div></details>;
}
function DeviceHistory({ id }: { id: string }) {
    const [minutes, setMinutes] = useState(60);
    return <><div className="page-heading"><p className="muted">Persisted observations. Gaps longer than two minutes break the line. Missing values are never replaced with zero.</p><label>Time range<select value={minutes} onChange={event => setMinutes(Number(event.target.value))}>{[[15, "15 minutes"], [60, "1 hour"], [360, "6 hours"], [1440, "24 hours"], [10080, "7 days"]].map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
        <DeviceRunCharts deviceId={id} /><div className="detail-grid">{[["battery_level", "Battery level", "ratio"], ...deviceCharts].map(([name, label, unit]) => <HistoryChart key={name} id={id} minutes={minutes} name={name} label={label} unit={unit} />)}</div></>;
}
