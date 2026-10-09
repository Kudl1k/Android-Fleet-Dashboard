import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FleetPage, { filterDevices, fleetGroup } from "./FleetPage";
import { type Device } from "../../lib/api";
const device = (name: string, state = "online"): Device => ({
    id: name,
    serial: name,
    name,
    state,
    connection_type: "wireless_adb",
    manufacturer: "Samsung",
    model: "SM-A356B",
    android_version: "16",
    root_available: false,
    capabilities: [],
    last_seen: null,
    host: null,
    port: null,
    auto_connect: true,
    error_code: null,
    error_message: null,
    retry_in_seconds: null,
});
function renderPage() {
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    return render(
        <QueryClientProvider client={client}>
            <MemoryRouter>
                <FleetPage />
            </MemoryRouter>
        </QueryClientProvider>,
    );
}
describe("fleet", () => {
    it("filters by model and state and sorts names", () => {
        const items = [
            device("Zed"),
            device("Alpha", "offline"),
            device("Broken", "unauthorized"),
        ];
        expect(
            filterDevices(items, "SM-A356B", "all", "name").map((d) => d.name),
        ).toEqual(["Alpha", "Broken", "Zed"]);
        expect(filterDevices(items, "", "offline", "name")).toHaveLength(1);
        expect(fleetGroup(items[2])).toBe("degraded");
    });
    it("shows loading then empty with no fabricated totals", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("[]")));
        renderPage();
        expect(screen.getByLabelText("Loading devices")).toBeInTheDocument();
        expect(
            await screen.findByText("Your fleet is ready for its first device"),
        ).toBeInTheDocument();
    });
    it("shows safe backend errors", async () => {
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError()));
        renderPage();
        expect(
            await screen.findByText("Could not load the fleet"),
        ).toBeInTheDocument();
    });
    it("withholds cached online metrics when the registry reports offline", async () => {
        vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/metrics") ? {device_id: "Alpha", state: "online", observed_at: "2026-10-09", stale: false, values: [{name: "battery_level", value: 0.7, unit: "ratio", labels: {}}]} : [device("Alpha", "offline")])))));
        renderPage();
        expect(await screen.findByText("Alpha")).toBeInTheDocument();
        expect(screen.queryByText("70.0%")).not.toBeInTheDocument();
        expect(screen.getAllByText("Unavailable")).toHaveLength(3);
    });
    it("renders disconnected values unavailable and supports live search", async () => {
        vi.stubGlobal(
            "fetch",
            vi
                .fn()
                .mockImplementation((url: string) =>
                    Promise.resolve(
                        new Response(
                            JSON.stringify(
                                url.endsWith("/metrics")
                                    ? {
                                          device_id: "Alpha",
                                          state: "offline",
                                          observed_at: null,
                                          stale: false,
                                          values: [],
                                      }
                                    : [device("Alpha", "offline")],
                            ),
                        ),
                    ),
                ),
        );
        renderPage();
        expect(await screen.findByText("Alpha")).toBeInTheDocument();
        expect(
            screen.getByText("Disconnected — telemetry unavailable"),
        ).toBeInTheDocument();
        expect(screen.getAllByText("Unavailable")).toHaveLength(3);
        fireEvent.change(
            screen.getByPlaceholderText("Name, model or IP address"),
            { target: { value: "absent" } },
        );
        expect(screen.getByText("No matching devices")).toBeInTheDocument();
    });
});
