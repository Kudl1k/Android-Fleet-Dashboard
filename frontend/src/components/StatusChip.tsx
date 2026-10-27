const tones: Record<string, string> = {
    succeeded: "ok",
    success: "ok",
    resolved: "ok",
    allowed: "ok",
    enabled: "ok",
    online: "ok",
    info: "info",
    running: "info",
    queued: "info",
    warning: "warn",
    pending: "warn",
    acknowledged: "warn",
    critical: "critical",
    firing: "critical",
    failed: "critical",
    error: "critical",
    timed_out: "critical",
    denied: "critical",
};

/** Text state with a coloured LED; the text always carries the meaning. */
export default function StatusChip({ value, label }: { value: string; label?: string }) {
    return (
        <span className="status-chip" data-tone={tones[value.toLowerCase()] ?? "off"}>
            <i aria-hidden="true" />
            {label ?? value.replaceAll("_", " ")}
        </span>
    );
}
