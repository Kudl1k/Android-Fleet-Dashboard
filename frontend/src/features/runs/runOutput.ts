/** Figures GNU `time -v` printed after the program finished. */
export interface TimeStats {
    elapsedSeconds: number | null;
    cpuPercent: number | null;
    userSeconds: number | null;
    systemSeconds: number | null;
    maxRssBytes: number | null;
    exitStatus: number | null;
}

export type RunPhase = "running" | "succeeded" | "failed" | "stopped";

export interface RunLike {
    state: string;
    output?: string | null;
    termination_reason?: string | null;
}

const MARKER = "\tCommand being timed:";

function field(report: string, label: string) {
    const line = report
        .split("\n")
        .find((item) => item.trim().startsWith(label + ":"));
    return line?.slice(line.indexOf(label + ":") + label.length + 1).trim();
}

function number(value: string | undefined) {
    if (value === undefined) return null;
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

/** "1:02:03.5" or "0:40.27" to seconds. */
function clock(value: string | undefined) {
    if (!value) return null;
    const parts = value.split(":").map(Number);
    if (parts.some((part) => !Number.isFinite(part))) return null;
    return parts.reduce((total, part) => total * 60 + part, 0);
}

/** Splits a recorded run's output into the program's own output and the timing report. */
export function parseRunOutput(output: string | null | undefined): {
    program: string;
    stats: TimeStats | null;
} {
    const text = output ?? "";
    const start = text.lastIndexOf(MARKER);
    if (start < 0) return { program: text, stats: null };
    const report = text.slice(start);
    const rss = number(field(report, "Maximum resident set size (kbytes)"));
    return {
        program: text.slice(0, start).replace(/\n$/, ""),
        stats: {
            elapsedSeconds: clock(
                field(report, "Elapsed (wall clock) time (h:mm:ss or m:ss)"),
            ),
            cpuPercent: number(field(report, "Percent of CPU this job got")),
            userSeconds: number(field(report, "User time (seconds)")),
            systemSeconds: number(field(report, "System time (seconds)")),
            maxRssBytes: rss === null ? null : rss * 1024,
            exitStatus: number(field(report, "Exit status")),
        },
    };
}

export function runPhase(run: RunLike): RunPhase {
    if (run.state === "active" || run.state === "connecting") return "running";
    if (run.state === "failed" || run.state === "timed_out") return "failed";
    const { stats } = parseRunOutput(run.output);
    if (stats?.exitStatus === 0) return "succeeded";
    if (stats && stats.exitStatus !== null) return "failed";
    return "stopped";
}

export function phaseLabel(run: RunLike) {
    const phase = runPhase(run);
    if (phase === "running") return "Running";
    if (phase === "succeeded") return "Finished";
    if (phase === "stopped") return "Stopped";
    const exit = parseRunOutput(run.output).stats?.exitStatus;
    if (exit !== null && exit !== undefined) return `Failed (exit ${exit})`;
    return run.state === "timed_out" ? "Timed out" : "Failed";
}

export function formatDuration(seconds: number) {
    if (seconds < 10) return `${seconds.toFixed(1)} s`;
    const total = Math.round(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h) return `${h} h ${m} min`;
    if (m) return `${m} min ${s} s`;
    return `${s} s`;
}
