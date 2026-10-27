import { useEffect, useState, type ReactNode } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogTitle,
} from "@/components/ui/dialog";
import { formatMetric } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import MetricChart, { deviceCharts } from "../telemetry/MetricChart";
import {
    loadRunTelemetry,
    type DeviceRecording,
} from "../terminal/RunTelemetry";
import {
    formatDuration,
    parseRunOutput,
    phaseLabel,
    runPhase,
    type RunLike,
} from "./runOutput";
import { summarizeRun } from "./runSummary";
import "./runs.css";

export interface RunRecord extends RunLike {
    id: string;
    device_id?: string | null;
    command?: string | null;
    owner?: string;
    created_at?: number;
    ended_at?: number | null;
    duration?: number;
    output_truncated?: boolean;
    device_recording?: DeviceRecording;
}

const TONES = {
    running: "info",
    succeeded: "ok",
    failed: "critical",
    stopped: "off",
} as const;

/** Status of a program run; a running run pulses. */
export function RunStatus({ run }: { run: RunLike }) {
    const phase = runPhase(run);
    return (
        <span
            className="status-chip run-status"
            data-tone={TONES[phase]}
            data-phase={phase}
        >
            <i aria-hidden="true" />
            {phaseLabel(run)}
        </span>
    );
}

/** Seconds since the run started, ticking while it is still running. */
export function useRunElapsed(run: RunRecord) {
    const running = runPhase(run) === "running";
    const [now, setNow] = useState(() => Date.now() / 1000);
    useEffect(() => {
        if (!running) return;
        const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
        return () => clearInterval(timer);
    }, [running]);
    if (running && run.created_at) return Math.max(0, now - run.created_at);
    return run.duration ?? 0;
}

export function downloadText(name: string, text: string, type: string) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
}

function percent(value: number | null) {
    return value === null ? null : `${(value * 100).toFixed(1)} %`;
}

function Stat({
    label,
    value,
    hint,
    tone,
}: {
    label: string;
    value: ReactNode;
    hint?: ReactNode;
    tone?: "ok" | "critical";
}) {
    return (
        <div className="run-stat" data-tone={tone}>
            <dt>{label}</dt>
            <dd>{value ?? <span className="muted">—</span>}</dd>
            {hint && <span className="run-stat-hint">{hint}</span>}
        </div>
    );
}

export default function RunDetail({
    run,
    deviceName,
    onClose,
}: {
    run: RunRecord;
    deviceName?: string;
    onClose: () => void;
}) {
    const auth = useAuth();
    const inRouter = useInRouterContext();
    const phase = runPhase(run);
    const running = phase === "running";
    const elapsed = useRunElapsed(run);
    const recording = run.device_recording?.enabled
        ? run.device_recording
        : undefined;
    const telemetry = useQuery({
        queryKey: ["run-telemetry", run.id, running],
        queryFn: ({ signal }) => loadRunTelemetry(run.id, signal),
        refetchInterval: running ? 10000 : false,
        staleTime: running ? 0 : Infinity,
        enabled: Boolean(recording) && auth.can("telemetry.read"),
    });
    const points = telemetry.data?.points ?? [];
    const summary = points.length ? summarizeRun(points) : undefined;
    const { program, stats } = parseRunOutput(run.output);
    const started = run.created_at
        ? new Date(run.created_at * 1000).toLocaleString()
        : undefined;
    const ceiling = summary?.lowestCeiling ?? null;
    return (
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open) onClose();
            }}
        >
            <DialogContent className="run-detail">
                <header className="run-detail-head">
                    <RunStatus run={run} />
                    <DialogTitle className="run-detail-title">
                        <code>{run.command ?? "Interactive session"}</code>
                    </DialogTitle>
                    <DialogDescription className="run-detail-meta">
                        {[
                            deviceName ?? run.device_id ?? "SSH host",
                            started && `started ${started}`,
                            run.owner && `by ${run.owner}`,
                        ]
                            .filter(Boolean)
                            .join(" · ")}
                    </DialogDescription>
                </header>

                <section aria-labelledby={`run-result-${run.id}`}>
                    <h3
                        className="run-section-title"
                        id={`run-result-${run.id}`}
                    >
                        Result
                    </h3>
                    <dl className="run-stats">
                        <Stat
                            label={running ? "Running for" : "Duration"}
                            value={formatDuration(
                                stats?.elapsedSeconds ?? elapsed,
                            )}
                            hint={running ? "updates live" : undefined}
                        />
                        <Stat
                            label="CPU used"
                            value={
                                stats?.cpuPercent != null
                                    ? `${stats.cpuPercent} %`
                                    : null
                            }
                            hint={
                                stats?.cpuPercent != null
                                    ? stats.cpuPercent > 100
                                        ? `about ${(stats.cpuPercent / 100).toFixed(1)} cores`
                                        : "of one core"
                                    : running
                                      ? "after it finishes"
                                      : undefined
                            }
                        />
                        <Stat
                            label="CPU time"
                            value={
                                stats &&
                                stats.userSeconds !== null &&
                                stats.systemSeconds !== null
                                    ? formatDuration(
                                          stats.userSeconds +
                                              stats.systemSeconds,
                                      )
                                    : null
                            }
                            hint={
                                stats &&
                                stats.userSeconds !== null &&
                                stats.systemSeconds !== null
                                    ? `${stats.userSeconds.toFixed(2)} s user · ${stats.systemSeconds.toFixed(2)} s system`
                                    : undefined
                            }
                        />
                        <Stat
                            label="Peak RAM"
                            value={
                                stats?.maxRssBytes != null
                                    ? formatMetric(stats.maxRssBytes, "bytes")
                                    : null
                            }
                            hint={
                                stats?.maxRssBytes != null
                                    ? "of the program"
                                    : running
                                      ? "after it finishes"
                                      : undefined
                            }
                        />
                        <Stat
                            label="Exit status"
                            value={stats?.exitStatus ?? null}
                            tone={
                                stats?.exitStatus == null
                                    ? undefined
                                    : stats.exitStatus === 0
                                      ? "ok"
                                      : "critical"
                            }
                            hint={
                                stats?.exitStatus === 0
                                    ? "success"
                                    : stats?.exitStatus != null
                                      ? "the program reported an error"
                                      : undefined
                            }
                        />
                    </dl>
                    {!running && !stats && (
                        <p className="muted run-note">
                            No timing report was saved. The run was stopped
                            before it finished, or GNU time is missing on the
                            SSH host.
                        </p>
                    )}
                </section>

                {recording && (
                    <section aria-labelledby={`run-device-${run.id}`}>
                        <h3
                            className="run-section-title"
                            id={`run-device-${run.id}`}
                        >
                            Device during the run
                        </h3>
                        <dl className="run-stats">
                            <Stat
                                label="CPU average / peak"
                                value={
                                    summary &&
                                    summary.cpuAverage !== null &&
                                    summary.cpuPeak !== null
                                        ? `${percent(summary.cpuAverage)} / ${percent(summary.cpuPeak)}`
                                        : null
                                }
                                hint="whole device"
                            />
                            <Stat
                                label="RAM peak"
                                value={
                                    summary?.memoryPeak != null
                                        ? formatMetric(
                                              summary.memoryPeak,
                                              "bytes",
                                          )
                                        : null
                                }
                                hint="whole device"
                            />
                            <Stat
                                label="Hottest sensor"
                                value={
                                    summary?.hottest != null
                                        ? formatMetric(
                                              summary.hottest,
                                              "celsius",
                                          )
                                        : null
                                }
                            />
                            <Stat
                                label="Throttled"
                                value={
                                    ceiling === null
                                        ? null
                                        : ceiling < 0.995
                                          ? `Yes, ${percent(ceiling)}`
                                          : "No"
                                }
                                hint={
                                    ceiling === null
                                        ? "not observed"
                                        : "lowest CPU frequency limit"
                                }
                            />
                            <Stat
                                label="Battery used"
                                value={
                                    summary?.batteryDrop != null
                                        ? `${(summary.batteryDrop * 100).toFixed(1)} pp`
                                        : null
                                }
                            />
                            <Stat
                                label="Samples"
                                value={
                                    summary?.samples ?? recording.sample_count
                                }
                                hint={`every ${recording.interval_seconds} s`}
                            />
                        </dl>
                        {recording.last_error && (
                            <p role="alert" className="error">
                                {recording.last_error}
                            </p>
                        )}
                        {telemetry.data?.truncated && (
                            <p role="alert">
                                Display limit reached; the CSV contains the
                                loaded samples only.
                            </p>
                        )}
                        <div className="detail-grid run-charts">
                            {deviceCharts.map(([name, title, unit]) => (
                                <MetricChart
                                    key={name}
                                    title={title}
                                    unit={unit}
                                    points={points.filter(
                                        (point) => point.name === name,
                                    )}
                                    loading={telemetry.isPending}
                                    error={
                                        telemetry.isError
                                            ? telemetry.error.message
                                            : undefined
                                    }
                                />
                            ))}
                        </div>
                        <p className="muted run-note">
                            Device-wide statistics include everything running on
                            the phone, not only this program. Slow collection or
                            disconnections leave gaps.
                        </p>
                    </section>
                )}

                <section aria-labelledby={`run-output-${run.id}`}>
                    <h3
                        className="run-section-title"
                        id={`run-output-${run.id}`}
                    >
                        Program output
                    </h3>
                    <pre className="run-output">
                        {program ||
                            (running ? "Waiting for output…" : "No output.")}
                    </pre>
                    {run.output_truncated && (
                        <p className="muted run-note">
                            Only the last 65,536 characters are retained.
                        </p>
                    )}
                </section>

                <footer className="run-detail-actions">
                    <Button
                        variant="outline"
                        onClick={() =>
                            downloadText(
                                `run-${run.id}.txt`,
                                run.output ?? "",
                                "text/plain",
                            )
                        }
                    >
                        <Download data-icon="inline-start" aria-hidden="true" />
                        Download results
                    </Button>
                    {recording && (
                        <Button
                            variant="outline"
                            disabled={!points.length}
                            onClick={() =>
                                downloadText(
                                    `device-statistics-${run.id}.csv`,
                                    [
                                        "observed_at,metric,value,unit,labels",
                                        ...points.map((point) =>
                                            [
                                                point.observed_at,
                                                point.name,
                                                String(point.value),
                                                point.unit,
                                                JSON.stringify(point.labels),
                                            ]
                                                .map(
                                                    (value) =>
                                                        `"${value.replaceAll('"', '""')}"`,
                                                )
                                                .join(","),
                                        ),
                                    ].join("\n"),
                                    "text/csv",
                                )
                            }
                        >
                            <Download
                                data-icon="inline-start"
                                aria-hidden="true"
                            />
                            Device statistics (CSV)
                        </Button>
                    )}
                    {run.device_id && inRouter && (
                        <Button variant="ghost" asChild>
                            <Link
                                to={`/devices/${encodeURIComponent(run.device_id)}`}
                            >
                                <ExternalLink
                                    data-icon="inline-start"
                                    aria-hidden="true"
                                />
                                Open device
                            </Link>
                        </Button>
                    )}
                </footer>
            </DialogContent>
        </Dialog>
    );
}
