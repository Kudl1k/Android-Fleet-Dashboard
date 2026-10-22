import {
    fireEvent,
    render,
    screen,
    waitFor,
    cleanup,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ManagementPage from "./ManagementPage";
import { request } from "../../lib/api";
vi.mock("../../lib/api", () => ({ request: vi.fn() }));
const defaultCan = (permission: string) =>
    Boolean(auth.token) && permission !== "security.manage";
const auth = { token: "", setToken: vi.fn(), can: defaultCan };
vi.mock("../../lib/auth", () => ({ useAuth: () => auth }));
vi.mock("../../lib/toast", () => ({ useToast: () => vi.fn() }));
const device = {
    id: "d1",
    name: "Samsung",
    host: "192.168.1.2",
    port: 5555,
    connection_type: "wireless_adb",
    auto_connect: false,
    state: "offline",
    error_code: "connection_refused",
    error_message: "Connection failed",
    retry_in_seconds: null,
};
function show() {
    render(
        <QueryClientProvider
            client={
                new QueryClient({
                    defaultOptions: {
                        queries: { retry: false },
                        mutations: { retry: false },
                    },
                })
            }
        >
            <MemoryRouter>
                <ManagementPage />
            </MemoryRouter>
        </QueryClientProvider>,
    );
}
afterEach(cleanup);
beforeEach(() => {
    vi.clearAllMocks();
    auth.can = defaultCan;
    HTMLDialogElement.prototype.showModal = vi.fn(function (
        this: HTMLDialogElement,
    ) {
        this.open = true;
    });
    auth.token = "";
});
describe("device management", () => {
    it("shows loading and empty states with mutation authentication", async () => {
        let resolve!: (value: never[]) => void;
        vi.mocked(request).mockImplementation(
            () =>
                new Promise((r) => {
                    resolve = r;
                }),
        );
        show();
        expect(screen.getByRole("status")).toHaveTextContent("Loading");
        expect(
            screen.getByRole("button", { name: "Register device" }),
        ).toBeDisabled();
        resolve([]);
        expect(
            await screen.findByText(/No registered devices/),
        ).toBeInTheDocument();
    });
    it("shows backend failure and retry", async () => {
        vi.mocked(request).mockRejectedValue(new Error("Backend unavailable"));
        show();
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "Backend unavailable",
        );
        expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    });
    it("registers a typed connection through the authenticated API", async () => {
        auth.token = "session";
        vi.mocked(request).mockResolvedValue([]);
        show();
        fireEvent.change(screen.getByLabelText("Device name"), {
            target: { value: "Kitchen" },
        });
        fireEvent.change(screen.getByLabelText("IP address or hostname"), {
            target: { value: "192.168.1.20" },
        });
        fireEvent.click(
            screen.getByRole("button", { name: "Register device" }),
        );
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/devices",
                expect.objectContaining({
                    method: "POST",
                    body: JSON.stringify({
                        name: "Kitchen",
                        host: "192.168.1.20",
                        port: 5555,
                        auto_connect: true,
                        connection_type: "wireless_adb",
                    }),
                }),
            ),
        );
    });
    it("requires confirmation before removal and exposes offline troubleshooting", async () => {
        auth.token = "session";
        vi.mocked(request).mockResolvedValue([device]);
        show();
        await screen.findByText("offline");
        fireEvent.click(screen.getByText("Connection troubleshooting"));
        expect(screen.getByText(/Connection failed/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Remove Samsung" }));
        expect(screen.getByRole("alertdialog")).toHaveTextContent(
            "Remove Samsung?",
        );
        expect(request).not.toHaveBeenCalledWith(
            "/api/v1/devices/d1",
            expect.objectContaining({ method: "DELETE" }),
        );
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm removal" }),
        );
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith("/api/v1/devices/d1", {
                method: "DELETE",
            }),
        );
    });

    it("lets administrators approve a pairing subnet in app settings", async () => {
        auth.token = "admin-session";
        auth.can = () => true;
        vi.mocked(request).mockImplementation(async (path, options) => {
            if (
                path === "/api/v1/pairing/allowed-networks" &&
                !options?.method
            ) {
                return { networks: [] } as never;
            }
            if (
                path === "/api/v1/pairing/allowed-networks" &&
                options?.method === "POST"
            ) {
                return {
                    networks: [
                        {
                            network: "10.42.0.0/24",
                            created_at: 1,
                            created_by: "admin",
                        },
                    ],
                } as never;
            }
            return [] as never;
        });
        show();
        fireEvent.change(await screen.findByLabelText("Private IP or CIDR"), {
            target: { value: "10.42.0.0/24" },
        });
        fireEvent.click(
            screen.getByRole("button", { name: "Approve network" }),
        );
        expect(await screen.findByText("10.42.0.0/24")).toBeInTheDocument();
        expect(request).toHaveBeenCalledWith(
            "/api/v1/pairing/allowed-networks",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({ network: "10.42.0.0/24" }),
            }),
        );
    });
    it("edits connection settings and requests reconnect without optimistic online state", async () => {
        auth.token = "session";
        vi.mocked(request).mockResolvedValue([device]);
        show();
        fireEvent.click(
            await screen.findByRole("button", { name: "Edit Samsung" }),
        );
        fireEvent.change(screen.getByLabelText("ADB connection port"), {
            target: { value: "42000" },
        });
        fireEvent.click(screen.getByLabelText("Automatically reconnect"));
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/devices/d1",
                expect.objectContaining({
                    method: "PATCH",
                    body: JSON.stringify({
                        name: "Samsung",
                        host: "192.168.1.2",
                        port: 42000,
                        connection_type: "wireless_adb",
                        auto_connect: true,
                    }),
                }),
            ),
        );
        fireEvent.click(
            screen.getByRole("button", { name: "Reconnect Samsung" }),
        );
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith("/api/v1/devices/d1/connect", {
                method: "POST",
            }),
        );
        expect(screen.getByText("offline")).toBeInTheDocument();
    });
});
