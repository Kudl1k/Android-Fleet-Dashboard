import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SettingsPage from "./SettingsPage";
import DeviceInterval from "../fleet/DeviceInterval";

let canManage = true;
vi.mock("../../lib/auth", () => ({ useAuth: () => ({ can: (p: string) => p === "device.read" || (canManage && p === "device.manage") }) }));
const toast = vi.fn();
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));

const setting = (value: number, overridden = false) => ({
    key: "metrics_interval_seconds", label: "Telemetry collection interval", description: "How often…",
    minimum: 5, maximum: 3600, default: 30, value, overridden, per_device: true,
});
let puts: { url: string; body: unknown }[] = [];
function serve(devices: Record<string, Record<string, number>> = {}) {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
            const body = JSON.parse(String(init.body));
            puts.push({ url, body });
            const value = body.values.metrics_interval_seconds;
            return new Response(JSON.stringify(url.includes("/devices/")
                ? { settings: [setting(30)], devices: value === null ? {} : { phone: { metrics_interval_seconds: value } } }
                : { settings: [setting(value ?? 30, value !== null)], devices }));
        }
        if (url === "/api/v1/settings") return new Response(JSON.stringify({ settings: [setting(30)], devices }));
        return new Response(JSON.stringify([{ id: "phone", name: "Galaxy A14", state: "online" }]));
    }));
}
function show(element: React.ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}><MemoryRouter>{element}</MemoryRouter></QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); puts = []; canManage = true; toast.mockClear(); });

describe("runtime settings", () => {
    it("validates and saves a fleet interval", async () => {
        serve();
        show(<SettingsPage />);
        const input = await screen.findByLabelText("Telemetry collection interval");
        expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
        fireEvent.change(input, { target: { value: "2" } });
        expect(input).toHaveAttribute("aria-invalid", "true");
        expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
        fireEvent.change(input, { target: { value: "10" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => expect(puts).toEqual([{ url: "/api/v1/settings", body: { values: { metrics_interval_seconds: 10 } } }]));
        expect(await screen.findByRole("button", { name: "Reset" })).toBeInTheDocument();
    });
    it("is read-only without the manage permission", async () => {
        canManage = false;
        serve({ phone: { metrics_interval_seconds: 5 } });
        show(<SettingsPage />);
        expect(await screen.findByLabelText("Telemetry collection interval")).toBeDisabled();
        expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
        expect(await screen.findByText("every 5 s")).toBeInTheDocument();
    });
    it("overrides and restores one device's collection interval", async () => {
        serve();
        show(<DeviceInterval deviceId="phone" />);
        const select = await screen.findByLabelText(/Collect every/);
        fireEvent.change(select, { target: { value: "5" } });
        await waitFor(() => expect(puts.at(-1)).toEqual({ url: "/api/v1/settings/devices/phone", body: { values: { metrics_interval_seconds: 5 } } }));
        await waitFor(() => expect(select).toHaveValue("5"));
        fireEvent.change(select, { target: { value: "" } });
        await waitFor(() => expect(puts.at(-1)?.body).toEqual({ values: { metrics_interval_seconds: null } }));
    });
});
