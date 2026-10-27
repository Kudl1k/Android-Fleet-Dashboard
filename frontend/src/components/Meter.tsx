import Sparkline from "./Sparkline";

/** A labelled horizontal gauge; a missing value renders an empty track, never zero. */
export default function Meter({
    label,
    value,
    display,
    warn = 0.75,
    critical = 0.9,
    invert = false,
    trend,
}: {
    label: string;
    value: number | null;
    display: string;
    warn?: number;
    critical?: number;
    /** Low values are the concern (battery). */
    invert?: boolean;
    trend?: number[];
}) {
    const level = value === null ? null : Math.min(1, Math.max(0, value));
    const concern = level === null ? 0 : invert ? 1 - level : level;
    const tone =
        level === null
            ? "none"
            : concern >= critical
              ? "critical"
              : concern >= warn
                ? "warn"
                : "ok";
    return (
        <div className="meter" data-tone={tone}>
            <span className="meter-label">
                {label}
                {trend && <Sparkline values={trend} />}
            </span>
            <strong className="meter-value">{display}</strong>
            <span className="meter-track" aria-hidden="true">
                {level !== null && (
                    <span
                        className="meter-fill"
                        style={{ width: `${level * 100}%` }}
                    />
                )}
            </span>
        </div>
    );
}
