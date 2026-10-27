import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import RunTelemetry, { loadRunTelemetry } from "./RunTelemetry";
import { request } from "../../lib/api";
vi.mock("../../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../../lib/api")>(), request: vi.fn() }));
vi.mock("../telemetry/MetricChart", async importOriginal => ({ ...await importOriginal<typeof import("../telemetry/MetricChart")>(), default: ({ title }: { title: string }) => <h3>{title}</h3> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("follows run telemetry pages with a fixed end", async () => {
    vi.mocked(request).mockResolvedValueOnce({ points: [{ name: "cpu_usage" }], next_cursor: "second" }).mockResolvedValueOnce({ points: [], next_cursor: null });
    const result = await loadRunTelemetry("run");
    expect(result.points).toHaveLength(1);
    const urls = vi.mocked(request).mock.calls.map(([url]) => new URL(url, "http://localhost"));
    expect(urls[0].searchParams.get("end")).toBe(urls[1].searchParams.get("end"));
    expect(urls[1].searchParams.get("cursor")).toBe("second");
});

it("refreshes at 15 seconds and fetches final observations when a run closes", async () => {
    vi.mocked(request).mockResolvedValue({ points: [], next_cursor: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const recording = { enabled: true, interval_seconds: 15, sample_count: 2, last_error: null, available_metrics: [] };
    const view = (active: boolean) => <QueryClientProvider client={client}><MemoryRouter><RunTelemetry sessionId="run" deviceId="phone" active={active} recording={recording} /></MemoryRouter></QueryClientProvider>;
    const mounted = render(view(true));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(client.getQueryCache().find({ queryKey: ["run-telemetry", "run", true] })?.options).toMatchObject({ refetchInterval: 15000 });
    expect(screen.getByText("CPU usage per core")).toBeInTheDocument();
    expect(screen.getByText("Temperatures")).toBeInTheDocument();
    expect(screen.getByText("NPU frequency")).toBeInTheDocument();
    mounted.rerender(view(false));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
});
