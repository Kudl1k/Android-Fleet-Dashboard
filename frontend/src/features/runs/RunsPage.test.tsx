import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RunsPage from "./RunsPage";

vi.mock("../../lib/auth", () => ({ useAuth: () => ({ can: () => true }) }));

const recording = { enabled: true, interval_seconds: 15, sample_count: 2, last_error: null, available_metrics: [] };
const runs = [
    { id: "r1", device_id: "a", command: "python yolo.py --model n", owner: "jirka", created_at: 1000, ended_at: 1030, duration: 30, state: "closed", device_recording: recording },
    { id: "r2", device_id: "a", command: "python yolo.py --model s", owner: "jirka", created_at: 2000, ended_at: 2060, duration: 60, state: "closed", device_recording: recording },
    { id: "r3", device_id: "a", command: "ls", owner: "jirka", created_at: 3000, ended_at: 3001, duration: 1, state: "closed" },
    { id: "shell", device_id: "a", command: null, owner: "jirka", created_at: 4000, ended_at: null, duration: 5, state: "active" },
];
const telemetry = (start: number, cpu: number) => ({
    points: [0, 15].map((offset) => ({ name: "cpu_usage", value: cpu, unit: "ratio", kind: "gauge", labels: {}, observed_at: new Date((start + offset) * 1000).toISOString() })),
    next_cursor: null,
});

function respond(url: string) {
    if (url.startsWith("/api/v1/terminal/sessions/r1/telemetry")) return telemetry(1000, 0.4);
    if (url.startsWith("/api/v1/terminal/sessions/r2/telemetry")) return telemetry(2000, 0.8);
    if (url.startsWith("/api/v1/terminal/sessions")) return { items: runs };
    return [{ id: "a", name: "Pixel 3a", state: "online" }];
}

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

describe("program runs", () => {
    it("lists program runs with summaries and compares two of them", async () => {
        vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(respond(url)), { status: 200 })));
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        render(<QueryClientProvider client={client}><MemoryRouter><RunsPage /></MemoryRouter></QueryClientProvider>);
        expect(await screen.findByText("3 runs, 2 with recorded statistics")).toBeInTheDocument();
        expect(screen.queryByText("shell")).not.toBeInTheDocument();
        expect(await screen.findByText("80.0% / 80.0%")).toBeInTheDocument();
        expect(screen.getByText("Statistics were not recorded for this run")).toBeInTheDocument();
        const boxes = screen.getAllByRole("checkbox");
        // Newest first: the unrecorded "ls" run cannot be compared.
        expect(boxes[0]).toBeDisabled();
        fireEvent.click(boxes[1]);
        fireEvent.click(boxes[2]);
        const comparison = await screen.findByRole("region", { name: "Run comparison" });
        expect(within(comparison).getAllByText(/Pixel 3a/).length).toBeGreaterThanOrEqual(2);
        expect(within(comparison).getByRole("heading", { name: "CPU usage" })).toBeInTheDocument();
    });
});
