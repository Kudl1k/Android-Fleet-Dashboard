import type { HistoryPoint } from "../../lib/api";
import { frequencyCeiling, groupThermal } from "../telemetry/series";

export interface RunSummary {
    samples: number;
    cpuAverage: number | null;
    cpuPeak: number | null;
    memoryPeak: number | null;
    hottest: number | null;
    batteryDrop: number | null;
    /** Lowest CPU frequency ceiling (ratio of maximum); below 1 means throttling occurred. */
    lowestCeiling: number | null;
}

function values(points: HistoryPoint[], name: string) {
    return points.filter((point) => point.name === name);
}

function byTime(points: HistoryPoint[]) {
    return [...points].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
}

/** Summarises recorded run telemetry; every figure is null when it was never observed. */
export function summarizeRun(points: HistoryPoint[]): RunSummary {
    const cpu = values(points, "cpu_usage").map((point) => point.value);
    const memory = values(points, "memory_used").map((point) => point.value);
    const thermal = groupThermal(values(points, "thermal_temperature"));
    const battery = byTime(values(points, "battery_level"));
    const ceiling = frequencyCeiling(
        values(points, "cpu_frequency_limit"),
        values(points, "cpu_max_frequency"),
    ).map((point) => point.value);
    return {
        samples: new Set(points.map((point) => point.observed_at)).size,
        cpuAverage: cpu.length ? cpu.reduce((sum, value) => sum + value, 0) / cpu.length : null,
        cpuPeak: cpu.length ? Math.max(...cpu) : null,
        memoryPeak: memory.length ? Math.max(...memory) : null,
        hottest: thermal.length ? Math.max(...thermal.map((point) => point.value)) : null,
        batteryDrop:
            battery.length >= 2 ? battery[0].value - battery[battery.length - 1].value : null,
        lowestCeiling: ceiling.length ? Math.min(...ceiling) : null,
    };
}

/**
 * Re-times run points to elapsed time since the run started, labelled by run, so
 * two runs can share one chart axis. The epoch base keeps HistoryPoint shape.
 */
export function alignRun(
    points: HistoryPoint[],
    name: string,
    startedAt: number,
    label: string,
    reduce?: (points: HistoryPoint[]) => HistoryPoint[],
): HistoryPoint[] {
    const selected = values(points, name);
    return (reduce ? reduce(selected) : selected).map((point) => ({
        ...point,
        // Renamed so charts treat it as an already-reduced comparison series.
        name: `compared_${point.name}`,
        observed_at: new Date(Date.parse(point.observed_at) - startedAt * 1000).toISOString(),
        labels: { group: label },
    }));
}

/** Hottest sensor at each instant, for comparing runs on one line each. */
export function hottestOverall(points: HistoryPoint[]): HistoryPoint[] {
    const hottest = new Map<string, HistoryPoint>();
    for (const point of points) {
        const current = hottest.get(point.observed_at);
        if (!current || point.value > current.value) hottest.set(point.observed_at, point);
    }
    return [...hottest.values()];
}
