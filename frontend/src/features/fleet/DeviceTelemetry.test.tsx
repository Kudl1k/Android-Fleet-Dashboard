import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DeviceTelemetry from "./DeviceTelemetry";
import type { CurrentMetrics, Metric } from "../../lib/api";

const metric = (
    name: string,
    value: number,
    unit: string,
    labels: Record<string, string> = {},
): Metric => ({ name, value, unit, labels, kind: "gauge" });
const collection = (values: Metric[]): CurrentMetrics => ({
    device_id: "device",
    state: "online",
    observed_at: "2026-10-21T10:00:00Z",
    stale: false,
    values,
});
describe("device observation lists", () => {
    it("retains real zeros, units, composite durations and complete sensor labels", () => {
        const sensor = "long_sensor_identity_".repeat(8);
        render(
            <DeviceTelemetry
                current={collection([
                    metric("cpu_usage", 0, "ratio"),
                    metric("cpu_frequency", 1200000000, "hertz", { sensor }),
                    metric("uptime", 86400, "seconds"),
                    metric("memory_used", 0, "bytes"),
                    metric("battery_health", 2, "enum"),
                ])}
            />,
        );
        fireOpen("Performance");
        fireOpen("Memory & storage");
        fireOpen("Battery & thermal");
        const performance = screen.getByRole("region", {
            name: "Performance observations",
        });
        expect(performance).toHaveAttribute("tabindex", "0");
        const definitions = within(performance).getAllByRole("definition");
        expect(definitions[0]).toHaveTextContent("0.0%");
        expect(definitions[1]).toHaveTextContent("1200 MHz");
        expect(definitions[2]).toHaveTextContent("1d 0h 0m");
        expect(
            within(performance).getByText(`sensor: ${sensor}`),
        ).toBeInTheDocument();
        expect(
            within(
                screen.getByRole("region", {
                    name: "Memory & storage observations",
                }),
            ).getByRole("definition"),
        ).toHaveTextContent("0.0 B");
        expect(
            within(
                screen.getByRole("region", {
                    name: "Battery & thermal observations",
                }),
            ).getByText("Good"),
        ).toBeInTheDocument();
        expect(
            within(performance).queryByText("Unavailable"),
        ).not.toBeInTheDocument();
    });
    it("keeps the scroll target mounted and the count outside it during observation updates", () => {
        const values = Array.from({ length: 80 }, (_, i) =>
            metric("cpu_core_usage", i / 100, "ratio", { core: String(i) }),
        );
        const view = render(<DeviceTelemetry current={collection(values)} />);
        fireOpen("Performance");
        const region = screen.getByRole("region", {
            name: "Performance observations",
        });
        region.scrollTop = 160;
        expect(
            within(region).queryByText("80 observations"),
        ).not.toBeInTheDocument();
        expect(screen.getByText("80 observations")).toBeInTheDocument();
        view.rerender(
            <DeviceTelemetry
                current={collection(
                    values.map((value) => ({ ...value, value: 0 })),
                )}
            />,
        );
        expect(
            screen.getByRole("region", { name: "Performance observations" }),
        ).toBe(region);
        expect(region.scrollTop).toBe(160);
        expect(within(region).getAllByRole("definition")).toHaveLength(80);
    });
});
function fireOpen(title: string) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(title) }));
}
