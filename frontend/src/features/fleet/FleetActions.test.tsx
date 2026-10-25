import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FleetPage from "./FleetPage";
import CommandPalette from "../../components/CommandPalette";
import { splitIdleInterfaces } from "./DeviceTelemetry";
import { type Device } from "../../lib/api";

const toast = vi.fn();
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));
vi.mock("../../lib/auth", () => ({
    useAuth: () => ({ can: (permission: string) => permission === "control.screen" || permission === "control.reboot" }),
}));

const device = (id: string, name: string, state = "online"): Device => ({
    id, serial: id, name, state, connection_type: "usb", manufacturer: "Google", model: "Pixel",
    android_version: "14", root_available: true, capabilities: [], last_seen: null, host: null,
    port: null, auto_connect: true, error_code: null, error_message: null, retry_in_seconds: null,
});
const devices = [device("a", "Alpha"), device("b", "Bravo"), device("c", "Charlie", "offline")];
const firing = { items: [{ id: "e1", severity: "critical", device_name: "Bravo", condition: "device_temperature", device_id: "b" }], total: 1 };
let posted: { url: string; body: unknown }[] = [];

function respond(url: string, init?: RequestInit) {
    if (init?.method === "POST") {
        posted.push({ url, body: JSON.parse(String(init.body)) });
        return { id: "op", state: "queued" };
    }
    if (url.startsWith("/api/v1/alerts")) return firing;
    if (url.includes("/metrics/history")) return { points: [], next_cursor: null };
    if (url.includes("/metrics")) return { device_id: "a", state: "online", observed_at: null, stale: false, values: [] };
    return devices;
}

function renderWith(element: React.ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={client}>
            <MemoryRouter>
                <Routes>
                    <Route path="/" element={element} />
                    <Route path="/devices/:id" element={<h1>Device page</h1>} />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    posted = [];
    toast.mockClear();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => new Response(JSON.stringify(respond(url, init)), { status: 200 })));
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

describe("fleet bulk actions", () => {
    it("queues one operation per selected online device", async () => {
        renderWith(<FleetPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Select devices" }));
        expect(screen.getByRole("checkbox", { name: "Select Charlie" })).toBeDisabled();
        fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Select Bravo" }));
        const bar = screen.getByRole("region", { name: "Bulk actions" });
        expect(within(bar).getByText("2 selected")).toBeInTheDocument();
        fireEvent.click(within(bar).getByRole("button", { name: "Wake screen" }));
        await waitFor(() => expect(posted).toHaveLength(2));
        expect(posted.map((p) => p.url)).toEqual(["/api/v1/devices/a/operations", "/api/v1/devices/b/operations"]);
        expect(posted[0].body).toEqual({ action: "screen.wake" });
        await waitFor(() => expect(toast).toHaveBeenCalledWith("Queued on 2 devices.", "success", { title: "Wake screen", href: "/operations" }));
    });

    it("requires confirmation before a bulk reboot", async () => {
        renderWith(<FleetPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Select devices" }));
        fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
        fireEvent.click(screen.getByRole("button", { name: "Reboot" }));
        const dialog = await screen.findByRole("alertdialog", { name: "Reboot 1 device?" });
        expect(posted).toHaveLength(0);
        fireEvent.click(within(dialog).getByRole("button", { name: "Reboot devices" }));
        await waitFor(() => expect(posted).toEqual([{ url: "/api/v1/devices/a/operations", body: { action: "reboot", confirmed: true } }]));
    });

    it("marks a card that has a firing alert", async () => {
        renderWith(<FleetPage />);
        expect(await screen.findByText("Alert: device temperature")).toBeInTheDocument();
    });
});

describe("fleet access and network display", () => {
    it("asks for sign-in instead of showing a raw permission error", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { message: "Permission denied" } }), { status: 403 })));
        const opened = vi.fn();
        window.addEventListener("fleet-open-access", opened);
        renderWith(<FleetPage />);
        expect(await screen.findByRole("heading", { name: "Sign in to view your fleet" })).toBeInTheDocument();
        expect(screen.queryByText("Permission denied")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
        expect(opened).toHaveBeenCalledTimes(1);
        window.removeEventListener("fleet-open-access", opened);
    });
    it("separates interfaces without traffic but keeps their real zeros", () => {
        const metric = (name: string, value: number, iface: string) => ({ name, value, unit: "bytes", kind: "counter", labels: { interface: iface } });
        const { active, idle } = splitIdleInterfaces([
            metric("network_receive", 100, "wlan0"),
            metric("network_transmit", 0, "wlan0"),
            metric("network_receive", 0, "rmnet0"),
            metric("network_transmit", 0, "rmnet0"),
        ]);
        expect(active.map((m) => m.labels.interface)).toEqual(["wlan0", "wlan0"]);
        expect(idle.map((m) => m.value)).toEqual([0, 0]);
    });
});

describe("command palette", () => {
    it("filters devices and pages and opens the chosen one", async () => {
        renderWith(<CommandPalette open onOpenChange={() => {}} routes={[{ label: "Alerts", path: "/alerts" }]} />);
        const input = await screen.findByRole("combobox", { name: "Search devices and pages" });
        await screen.findByRole("option", { name: /Bravo/ });
        fireEvent.change(input, { target: { value: "brav" } });
        expect(screen.getAllByRole("option")).toHaveLength(1);
        fireEvent.keyDown(input, { key: "Enter" });
        expect(await screen.findByRole("heading", { name: "Device page" })).toBeInTheDocument();
    });
});
