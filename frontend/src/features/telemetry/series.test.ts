import { describe, expect, it } from "vitest";
import type { HistoryPoint } from "../../lib/api";
import { decimate, frequencyCeiling, groupThermal } from "./series";
import { spansBelow } from "./MetricChart";

const at = (seconds: number) => new Date(seconds * 1000).toISOString();
const point = (name: string, seconds: number, value: number, labels: Record<string, string>, unit = "celsius"): HistoryPoint => ({
    name, observed_at: at(seconds), value, labels, unit, kind: "gauge",
});

describe("chart series helpers", () => {
    it("groups thermal zones by type, keeping the hottest reading", () => {
        const grouped = groupThermal([
            point("thermal_temperature", 0, 40, { sensor: "cpu0", type: "cpu" }),
            point("thermal_temperature", 0, 46, { sensor: "cpu7", type: "cpu" }),
            point("thermal_temperature", 0, 33, { sensor: "battery", type: "battery" }),
        ]);
        expect(grouped.map((p) => [p.labels.group, p.value]).sort()).toEqual([["Battery", 33], ["CPU", 46]]);
    });
    it("reports the lowest frequency ceiling across cores", () => {
        const ceiling = frequencyCeiling(
            [point("cpu_frequency_limit", 0, 1.8e9, { core: "0" }, "hertz"), point("cpu_frequency_limit", 0, 1.2e9, { core: "7" }, "hertz")],
            [point("cpu_max_frequency", 0, 1.8e9, { core: "0" }, "hertz"), point("cpu_max_frequency", 0, 2.4e9, { core: "7" }, "hertz")],
        );
        expect(ceiling).toHaveLength(1);
        expect(ceiling[0].value).toBeCloseTo(0.5);
        expect(frequencyCeiling([point("cpu_frequency_limit", 0, 1e9, { core: "0" }, "hertz")], [])).toEqual([]);
    });
    it("decimates long series but keeps offline gaps", () => {
        const rows = Array.from({ length: 1000 }, (_, i) => ({ time: i, s0: i % 2 }));
        rows.splice(500, 0, { time: 499.5, s0: null as unknown as number });
        const result = decimate(rows, ["s0"], 100);
        expect(result.length).toBeLessThanOrEqual(110);
        expect(result.some((row) => row.s0 === null)).toBe(true);
        expect(decimate(rows.slice(0, 50), ["s0"], 100)).toHaveLength(50);
    });
    it("finds throttled spans below a threshold", () => {
        const rows = [{ time: 0, s0: 100 }, { time: 1, s0: 80 }, { time: 2, s0: 70 }, { time: 3, s0: 100 }, { time: 4, s0: 90 }];
        expect(spansBelow(rows, "s0", 99.5)).toEqual([[1, 2], [4, 4]]);
    });
});
