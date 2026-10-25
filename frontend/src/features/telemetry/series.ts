import type { HistoryPoint } from "../../lib/api";

export type ChartRow = Record<string, number | null>;

const thermalNames: Record<string, string> = {
    cpu: "CPU",
    gpu: "GPU",
    npu: "NPU",
    battery: "Battery",
    skin: "Skin (surface)",
    usb: "USB port",
    power_amplifier: "Modem amplifier",
    unknown: "Other zones",
};

export function thermalGroupName(type: string | undefined) {
    return thermalNames[type ?? "unknown"] ?? type ?? "Other zones";
}

/**
 * Collapses dozens of thermal zones into one series per sensor type, keeping the
 * hottest reading at each instant. Missing types simply produce no series.
 */
export function groupThermal(points: HistoryPoint[]): HistoryPoint[] {
    const hottest = new Map<string, HistoryPoint>();
    for (const point of points) {
        const group = thermalGroupName(point.labels.type);
        const key = `${point.observed_at}|${group}`;
        const current = hottest.get(key);
        if (!current || point.value > current.value)
            hottest.set(key, { ...point, labels: { group } });
    }
    return [...hottest.values()];
}

/**
 * Lowest CPU frequency ceiling across cores as a ratio of hardware maximum.
 * 1 means no core is capped; values below 1 indicate thermal or policy throttling.
 */
export function frequencyCeiling(limits: HistoryPoint[], maxima: HistoryPoint[]): HistoryPoint[] {
    const maximum = new Map<string, number>();
    for (const point of maxima) {
        const core = point.labels.core ?? "";
        maximum.set(core, Math.max(maximum.get(core) ?? 0, point.value));
    }
    const lowest = new Map<string, HistoryPoint>();
    for (const point of limits) {
        const top = maximum.get(point.labels.core ?? "");
        if (!top) continue;
        const ratio = Math.min(1, point.value / top);
        const current = lowest.get(point.observed_at);
        if (!current || ratio < current.value)
            lowest.set(point.observed_at, {
                ...point,
                name: "cpu_frequency_ceiling",
                unit: "ratio",
                value: ratio,
                labels: {},
            });
    }
    return [...lowest.values()];
}

function isGap(row: ChartRow, keys: string[]) {
    return keys.every((key) => row[key] === null);
}

/**
 * Averages neighbouring rows so a chart never draws more than about `limit` points.
 * Gap rows are kept, so offline periods still break the line.
 */
export function decimate(data: ChartRow[], keys: string[], limit = 300): ChartRow[] {
    if (data.length <= limit) return data;
    const size = Math.ceil(data.length / limit);
    const result: ChartRow[] = [];
    let bucket: ChartRow[] = [];
    const flush = () => {
        if (!bucket.length) return;
        const row: ChartRow = { time: bucket[0].time };
        for (const key of keys) {
            const values = bucket.map((item) => item[key]).filter((value): value is number => value !== null);
            row[key] = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
        }
        result.push(row);
        bucket = [];
    };
    for (const row of data) {
        if (isGap(row, keys)) {
            flush();
            result.push(row);
            continue;
        }
        bucket.push(row);
        if (bucket.length === size) flush();
    }
    flush();
    return result;
}
