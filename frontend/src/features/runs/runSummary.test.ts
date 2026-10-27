import { describe, expect, it } from "vitest";
import type { HistoryPoint } from "../../lib/api";
import { alignRun, hottestOverall, summarizeRun } from "./runSummary";

const p = (name: string, seconds: number, value: number, labels: Record<string, string> = {}, unit = "ratio"): HistoryPoint => ({
    name, observed_at: new Date(seconds * 1000).toISOString(), value, labels, unit, kind: "gauge",
});

describe("run summaries", () => {
    it("summarises observed values and leaves unobserved ones empty", () => {
        const summary = summarizeRun([
            p("cpu_usage", 100, 0.5), p("cpu_usage", 115, 0.9),
            p("battery_level", 100, 0.8), p("battery_level", 115, 0.75),
            p("thermal_temperature", 100, 41, { sensor: "a", type: "cpu" }, "celsius"),
            p("thermal_temperature", 115, 47, { sensor: "b", type: "gpu" }, "celsius"),
        ]);
        expect(summary.samples).toBe(2);
        expect(summary.cpuAverage).toBeCloseTo(0.7);
        expect(summary.cpuPeak).toBe(0.9);
        expect(summary.hottest).toBe(47);
        expect(summary.batteryDrop).toBeCloseTo(0.05);
        expect(summary.memoryPeak).toBeNull();
        expect(summary.lowestCeiling).toBeNull();
    });
    it("detects throttling from frequency ceilings", () => {
        const summary = summarizeRun([
            p("cpu_max_frequency", 0, 2e9, { core: "0" }, "hertz"),
            p("cpu_frequency_limit", 0, 2e9, { core: "0" }, "hertz"),
            p("cpu_frequency_limit", 15, 1.5e9, { core: "0" }, "hertz"),
        ]);
        expect(summary.lowestCeiling).toBeCloseTo(0.75);
    });
    it("aligns runs to elapsed time under one label", () => {
        const aligned = alignRun([p("cpu_usage", 1000, 0.4), p("memory_used", 1000, 5)], "cpu_usage", 990, "A: Pixel");
        expect(aligned).toHaveLength(1);
        expect(Date.parse(aligned[0].observed_at)).toBe(10000);
        expect(aligned[0].labels).toEqual({ group: "A: Pixel" });
        expect(hottestOverall([p("t", 0, 30), p("t", 0, 50), p("t", 5, 20)]).map((x) => x.value)).toEqual([50, 20]);
    });
});
