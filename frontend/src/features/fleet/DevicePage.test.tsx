import { describe, expect, it } from "vitest";
import { chartPoints } from "./DevicePage";
import type { HistoryPoint } from "../../lib/api";
const point = (time: string, value: number): HistoryPoint => ({name: "cpu_usage", value, unit: "ratio", kind: "gauge", labels: {}, observed_at: time});
describe("historical chart observations", () => {
    it("preserves real zeros and converts ratios to percentages", () => {
        expect(chartPoints([point("2026-10-09T10:00:00Z", 0), point("2026-10-09T10:00:30Z", 0.42)]).map(p => p.value)).toEqual([0, 42]);
    });
    it("breaks lines across collection gaps without fabricating zeros", () => {
        const points = chartPoints([point("2026-10-09T10:00:00Z", 0.42), point("2026-10-09T10:05:00Z", 0.5)]);
        expect(points.map(p => p.value)).toEqual([42, null, 50]);
    });
    it("keeps missing histories empty", () => { expect(chartPoints([])).toEqual([]); });
});
