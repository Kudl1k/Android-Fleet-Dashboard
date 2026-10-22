import { describe, expect, it } from "vitest";
import { chartPoints } from "./DevicePage";
import type { HistoryPoint } from "../../lib/api";
const point = (time: string, value: number): HistoryPoint => ({
    name: "cpu_usage",
    value,
    unit: "ratio",
    kind: "gauge",
    labels: {},
    observed_at: time,
});
describe("historical chart observations", () => {
    it("preserves real zeros and converts ratios to percentages", () => {
        expect(
            chartPoints([
                point("2026-10-09T10:00:00Z", 0),
                point("2026-10-09T10:00:30Z", 0.42),
            ]).map((p) => p.value),
        ).toEqual([0, 42]);
    });
    it("breaks lines across collection gaps without fabricating zeros", () => {
        const points = chartPoints([
            point("2026-10-09T10:00:00Z", 0.42),
            point("2026-10-09T10:05:00Z", 0.5),
        ]);
        expect(points.map((p) => p.value)).toEqual([42, null, 50]);
    });
    it("keeps missing histories empty", () => {
        expect(chartPoints([])).toEqual([]);
    });
});

import { vi, beforeEach } from "vitest";
import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DevicePage from "./DevicePage";
import { PollContext } from "../../lib/hooks";
import type { CurrentMetrics, Device } from "../../lib/api";

// Isolate page organization from hardware protocols; the real tools have their own suites.
vi.mock("../screen/LiveScreen", () => ({
    default: () => <button>Start mock screen</button>,
}));
vi.mock("../terminal/TerminalPanel", () => ({
    default: () => <input aria-label="Terminal session draft" />,
}));
vi.mock("../control/DeviceSetup", () => ({
    default: () => <button>Optional setup</button>,
}));
vi.mock("../control/DeviceControl", () => ({
    default: () => <button>Device action</button>,
}));
vi.mock("../management/AdbTcpSwitch", () => ({
    default: () => <button>Switch transport</button>,
}));
vi.mock("../terminal/DeviceRunCharts", () => ({
    default: () => <p>Recorded runs</p>,
}));
vi.mock("../telemetry/MetricChart", () => ({
    deviceCharts: [["cpu_usage", "CPU history", "ratio"]],
    default: () => <p>History chart</p>,
}));
const d: Device = {
    id: "demo",
    name: "Warehouse scanner",
    serial: "serial",
    state: "online",
    connection_type: "wireless_adb",
    manufacturer: "Samsung",
    model: "A35",
    android_version: "16",
    root_available: false,
    capabilities: [],
    last_seen: null,
    host: "192.168.1.2",
    port: 5555,
    auto_connect: true,
    error_code: null,
    error_message: null,
    retry_in_seconds: null,
};
const m: CurrentMetrics = {
    device_id: "demo",
    state: "online",
    stale: false,
    observed_at: "2026-10-21T10:00:00Z",
    values: [
        {
            name: "cpu_usage",
            value: 0,
            unit: "ratio",
            kind: "gauge",
            labels: {},
        },
        {
            name: "network_receive",
            value: 0,
            unit: "bytes",
            kind: "counter",
            labels: { interface: "wlan0" },
        },
    ],
};
let deviceData: Device;
let metricsData: CurrentMetrics;
let metricsFail: boolean;
let deviceFail: boolean;
let holdMetrics: boolean;
function renderDevice(polling = 15000) {
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    const page = render(
        <QueryClientProvider client={client}>
            <PollContext.Provider value={polling}>
                <MemoryRouter initialEntries={["/devices/demo"]}>
                    <Routes>
                        <Route path="/devices/:id" element={<DevicePage />} />
                    </Routes>
                </MemoryRouter>
            </PollContext.Provider>
        </QueryClientProvider>,
    );
    return { ...page, client };
}
beforeEach(() => {
    deviceData = { ...d };
    metricsData = { ...m };
    metricsFail = false;
    deviceFail = false;
    holdMetrics = false;
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) => {
            if (url.endsWith("/metrics") && holdMetrics)
                return new Promise<Response>(() => {});
            const failed = url.endsWith("/metrics") ? metricsFail : deviceFail;
            return Promise.resolve(
                new Response(
                    JSON.stringify(
                        failed
                            ? { error: { message: "Manager check failed" } }
                            : url.includes("/history?")
                              ? { points: [], next_cursor: null }
                              : url.endsWith("/metrics")
                                ? metricsData
                                : deviceData,
                    ),
                    { status: failed ? 503 : 200 },
                ),
            );
        }),
    );
});
describe("device workspace", () => {
    it("prioritizes identity, freshness, real zeros and grouped availability", async () => {
        renderDevice();
        expect(
            await screen.findByText("Telemetry current"),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("heading", { level: 1, name: d.name }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("link", { name: "Manage device" }),
        ).toHaveAttribute("href", "/management?device=demo");
        expect(screen.getAllByText("0.0%").length).toBeGreaterThan(0);
        const availability = screen.getByRole("button", {
            name: /Metric availability/,
        });
        expect(availability).toHaveAttribute("aria-expanded", "false");
        fireEvent.click(availability);
        expect(availability).toHaveAttribute("aria-expanded", "true");
        expect(
            within(availability.parentElement!).getByText("GPU utilization"),
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Cumulative interface counters/),
        ).toBeInTheDocument();
        expect(screen.getAllByText(/Last successful collection/)).toHaveLength(
            1,
        );
    });
    it.each([
        ["disconnected", { state: "offline" }, {}, "Device disconnected"],
        ["stale", {}, { stale: true }, "Telemetry stale"],
        [
            "snapshot disconnected",
            {},
            { state: "offline" },
            "Telemetry connection not confirmed",
        ],
        [
            "no collection",
            {},
            { observed_at: null },
            "Waiting for first collection",
        ],
        ["empty", {}, { values: [] }, "No observations collected"],
    ])(
        "withholds values for %s",
        async (_name, devicePatch, metricPatch, message) => {
            deviceData = { ...d, ...devicePatch };
            metricsData = { ...m, ...metricPatch };
            renderDevice();
            expect(await screen.findByText(message)).toBeInTheDocument();
            expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
            expect(
                screen.queryByText(/Metric availability/),
            ).not.toBeInTheDocument();
            expect(
                screen.getByText("Historical telemetry"),
            ).toBeInTheDocument();
        },
    );
    it("shows partial memory observations without inventing a utilization ratio", async () => {
        metricsData = {
            ...m,
            values: [
                {
                    name: "memory_used",
                    value: 0,
                    unit: "bytes",
                    kind: "gauge",
                    labels: {},
                },
                {
                    name: "memory_total",
                    value: 0,
                    unit: "bytes",
                    kind: "gauge",
                    labels: {},
                },
            ],
        };
        renderDevice();
        await screen.findByText("Telemetry current");
        const overview = screen.getAllByRole("definition")[0].closest("dl")!;
        expect(within(overview).getByText("RAM used")).toBeInTheDocument();
        expect(within(overview).getByText("0.0 B")).toBeInTheDocument();
        expect(screen.queryByText("RAM utilization")).not.toBeInTheDocument();
    });
    it("surfaces an available observation for a sparse collection", async () => {
        metricsData = { ...m, values: [m.values[1]] };
        renderDevice();
        await screen.findByText("Telemetry current");
        const overview = screen.getAllByRole("definition")[0].closest("dl")!;
        expect(within(overview).getByText("Received")).toBeInTheDocument();
        expect(within(overview).getByText("0.0 B")).toBeInTheDocument();
        expect(
            within(overview).getByText(/Cumulative counter/),
        ).toBeInTheDocument();
    });
    it("distinguishes loading from empty observations", async () => {
        holdMetrics = true;
        renderDevice();
        expect(
            await screen.findByText("Loading telemetry…"),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: "Refreshing…" }),
        ).toBeDisabled();
        expect(
            screen.queryByText("No current values to display."),
        ).not.toBeInTheDocument();
    });
    it("recovers a metrics request failure through Refresh status", async () => {
        metricsFail = true;
        renderDevice();
        expect(
            await screen.findByText("Telemetry request failed"),
        ).toBeInTheDocument();
        metricsFail = false;
        fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
        expect(
            await screen.findByText("Telemetry current"),
        ).toBeInTheDocument();
    });
    it("withholds cached values when a later connection check fails", async () => {
        renderDevice();
        await screen.findByText("Telemetry current");
        deviceFail = true;
        fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
        expect(
            await screen.findByText("Connection check failed"),
        ).toBeInTheDocument();
        expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
        expect(screen.getByText("Connection unknown")).toBeInTheDocument();
    });
    it("explains paused refresh without claiming the saved collection is current", async () => {
        renderDevice(0);
        expect(
            await screen.findByText("Telemetry refresh paused"),
        ).toBeInTheDocument();
        expect(screen.queryByText("Telemetry current")).not.toBeInTheDocument();
        expect(screen.getAllByText("0.0%").length).toBeGreaterThan(0);
    });
    it("keeps tool state mounted across disclosure changes and polling", async () => {
        const { client } = renderDevice();
        await screen.findByText("Telemetry current");
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Device tools" }), {
            button: 0,
            ctrlKey: false,
        });
        const terminal = screen.getByRole("button", {
            name: /Terminal ADB shell/,
        });
        const draft = screen.getByLabelText("Terminal session draft");
        fireEvent.click(terminal);
        fireEvent.change(draft, { target: { value: "session draft" } });
        fireEvent.click(terminal);
        await client.invalidateQueries({ queryKey: ["device", "demo"] });
        fireEvent.click(terminal);
        expect(screen.getByLabelText("Terminal session draft")).toBe(draft);
        expect(draft).toHaveValue("session draft");
        expect(screen.getByText("Start mock screen")).toBeInTheDocument();
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Overview" }), {
            button: 0,
            ctrlKey: false,
        });
        expect(draft).not.toBeVisible();
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Device tools" }), {
            button: 0,
            ctrlKey: false,
        });
        expect(draft).toHaveValue("session draft");
        expect(screen.getByText("Optional setup")).toBeInTheDocument();
        expect(screen.getByText("Switch transport")).toBeInTheDocument();
    });
    it("loads history on demand and preserves its range across collapse", async () => {
        renderDevice();
        await screen.findByText("Telemetry current");
        expect(screen.queryByLabelText("Time range")).not.toBeInTheDocument();
        const summary = screen.getByRole("tab", { name: "History" });
        fireEvent.mouseDown(summary, { button: 0, ctrlKey: false });
        const range = await screen.findByLabelText("Time range");
        fireEvent.change(range, { target: { value: "10080" } });
        await waitFor(() =>
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining("metric=cpu_usage"),
                expect.anything(),
            ),
        );
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Overview" }), {
            button: 0,
            ctrlKey: false,
        });
        fireEvent.mouseDown(summary, { button: 0, ctrlKey: false });
        expect(range).toHaveValue("10080");
    });
});

it("moves between workspace tabs with arrow keys without exposing inactive tools", async () => {
    renderDevice();
    await screen.findByText("Telemetry current");
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    await waitFor(() =>
        expect(screen.getByRole("tab", { name: "History" })).toHaveFocus(),
    );
    expect(await screen.findByLabelText("Time range")).toBeVisible();
    expect(screen.getByLabelText("Terminal session draft")).not.toBeVisible();
    fireEvent.keyDown(screen.getByRole("tab", { name: "History" }), {
        key: "ArrowRight",
    });
    await waitFor(() =>
        expect(screen.getByRole("tab", { name: "Device tools" })).toHaveFocus(),
    );
    expect(
        screen.getByRole("button", { name: /Terminal ADB shell/ }),
    ).toBeVisible();
});
