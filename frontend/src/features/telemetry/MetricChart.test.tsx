import { describe, expect, it } from "vitest";
import { metricSeries } from "./MetricChart";
import type { HistoryPoint } from "../../lib/api";

const point = (seconds: number, value: number, labels: Record<string, string>): HistoryPoint => ({
    name: "cpu_core_usage", observed_at: new Date(seconds * 1000).toISOString(), value,
    labels, unit: "ratio", kind: "gauge",
});
describe("separate metric chart series", () => {
    it("keeps cores at the same time separate and preserves zero", () => {
        const chart = metricSeries([point(0, 0, { core: "0" }), point(0, 0.8, { core: "1" })]);
        expect(chart.series.map(item => item.label)).toEqual(["core: 0", "core: 1"]);
        expect(chart.data).toEqual([{ time: 0, s0: 0, s1: 80 }]);
    });
    it("breaks missing core readings and offline gaps without connecting unrelated sensors", () => {
        const chart = metricSeries([point(0, 0.1, { core: "0" }), point(0, 0.8, { core: "1" }), point(15, 0.2, { core: "0" }), point(300, 0.3, { core: "0" })]);
        expect(chart.data[1]).toEqual({ time: 15000, s0: 20, s1: null });
        expect(chart.data[2]).toEqual({ time: 15001, s0: null, s1: null });
    });
    it("canonicalizes sensor labels and sorts observations", () => {
        const chart = metricSeries([point(15, 0.4, { sensor: "CPU", type: "cpu" }), point(0, 0.3, { type: "cpu", sensor: "CPU" })]);
        expect(chart.series).toHaveLength(1);
        expect(chart.data.map(row => row.time)).toEqual([0, 15000]);
    });
});
