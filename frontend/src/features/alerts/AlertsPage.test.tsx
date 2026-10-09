import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AlertsPage from "./AlertsPage";
import { request } from "../../lib/api";
vi.mock("../../lib/api", () => ({ request: vi.fn() }));
const auth = { token: "", setToken: vi.fn(), can: () => Boolean(auth.token) };
const toast = vi.fn();
vi.mock("../../lib/auth", () => ({ useAuth: () => auth }));
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));
const event = {
    id: "a1",
    rule_id: "r1",
    device_id: "d1",
    device_name: "Samsung",
    condition: "battery_low",
    severity: "warning",
    threshold: 0.2,
    value: null,
    state: "firing",
    started_at: "2026-10-09T10:00:00Z",
    fired_at: "2026-10-09T10:01:00Z",
    updated_at: "2026-10-09T10:01:00Z",
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
                <AlertsPage />
            </MemoryRouter>
        </QueryClientProvider>,
    );
}
afterEach(cleanup);
beforeEach(() => {
    vi.clearAllMocks();
    auth.token = "";
    vi.mocked(request).mockImplementation(async (path) =>
        path.endsWith("/devices") || path.endsWith("/rules")
            ? []
            : { items: [], total: 0, limit: 50, offset: 0 },
    );
});
describe("alerts", () => {
    it("shows empty alerts and no rules", async () => {
        show();
        expect(
            await screen.findByText("No alerts match these filters."),
        ).toBeInTheDocument();
        expect(
            await screen.findByText("No alert rules configured."),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: "Create rule" }),
        ).toBeDisabled();
    });
    it("reports backend failure without fabricating counts", async () => {
        vi.mocked(request).mockRejectedValue(new Error("Backend unavailable"));
        show();
        expect(
            await screen.findByText("Unavailable active alerts"),
        ).toBeInTheDocument();
        expect(await screen.findAllByRole("alert")).toHaveLength(3);
    });
    it("shows unsupported observed value, guards acknowledge and suppresses initial notifications", async () => {
        vi.mocked(request).mockImplementation(async (path) =>
            path.endsWith("/devices") || path.endsWith("/rules")
                ? []
                : { items: [event], total: 1, limit: 50, offset: 0 },
        );
        show();
        expect(
            await screen.findByText("Observed: Unavailable"),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: /Acknowledge Samsung/ }),
        ).toBeDisabled();
        expect(toast).not.toHaveBeenCalled();
    });
    it("acknowledges and filters using server API", async () => {
        auth.token = "session";
        vi.mocked(request).mockImplementation(async (path) =>
            path.endsWith("/devices") || path.endsWith("/rules")
                ? []
                : { items: [event], total: 1, limit: 50, offset: 0 },
        );
        show();
        fireEvent.click(
            await screen.findByRole("button", { name: /Acknowledge Samsung/ }),
        );
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/alerts/a1/acknowledge",
                { method: "POST" },
            ),
        );
        fireEvent.change(screen.getByLabelText("Severity"), {
            target: { value: "critical" },
        });
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/alerts?limit=50&offset=0&state=firing&severity=critical",
                expect.objectContaining({ signal: expect.any(AbortSignal) }),
            ),
        );
    });
    it("creates a per-device sustained rule with recovery hysteresis", async () => {
        auth.token = "session";
        vi.mocked(request).mockImplementation(async (path) =>
            path.endsWith("/devices")
                ? [{ id: "d1", name: "Samsung" }]
                : path.endsWith("/rules")
                  ? []
                  : { items: [], total: 0, limit: 50, offset: 0 },
        );
        show();
        await screen.findByText("No alert rules configured.");
        fireEvent.change(screen.getByLabelText("Rule name"), {
            target: { value: "Battery watch" },
        });
        fireEvent.change(screen.getByLabelText("Rule scope"), {
            target: { value: "d1" },
        });
        fireEvent.change(screen.getByLabelText("Rule severity"), {
            target: { value: "critical" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/alerts/rules",
                expect.objectContaining({
                    method: "POST",
                    body: JSON.stringify({
                        name: "Battery watch",
                        condition: "battery_low",
                        device_id: "d1",
                        severity: "critical",
                        threshold: 0.2,
                        duration_seconds: 60,
                        hysteresis: 0.05,
                        enabled: true,
                    }),
                }),
            ),
        );
    });
    it("uses high utilization defaults and retains an unfinished rule while acknowledging", async () => {
        auth.token = "session";
        vi.mocked(request).mockImplementation(async (path) =>
            path.endsWith("/devices") || path.endsWith("/rules")
                ? []
                : { items: [event], total: 1, limit: 50, offset: 0 },
        );
        show();
        await screen.findByText("Observed: Unavailable");
        fireEvent.change(screen.getByLabelText("Rule name"), {
            target: { value: "CPU watch" },
        });
        fireEvent.change(screen.getByLabelText("Condition"), {
            target: { value: "cpu_high" },
        });
        expect(screen.getByLabelText("Threshold (ratio (0–1))")).toHaveValue(0.9);
        fireEvent.click(screen.getByRole("button", { name: /Acknowledge Samsung/ }));
        await waitFor(() => expect(toast).toHaveBeenCalledWith("Alert acknowledged", "success"));
        expect(screen.getByLabelText("Rule name")).toHaveValue("CPU watch");
    });
    it("loads an existing rule for editing and confirms deletion", async () => {
        HTMLDialogElement.prototype.showModal = vi.fn(function (
            this: HTMLDialogElement,
        ) {
            this.open = true;
        });
        auth.token = "session";
        const rule = {
            id: "r1",
            name: "Battery watch",
            condition: "battery_low",
            device_id: null,
            severity: "warning",
            threshold: 0.2,
            duration_seconds: 60,
            hysteresis: 0.05,
            enabled: true,
        };
        vi.mocked(request).mockImplementation(async (path) =>
            path.endsWith("/rules")
                ? [rule]
                : path.endsWith("/devices")
                  ? []
                  : { items: [], total: 0, limit: 50, offset: 0 },
        );
        show();
        fireEvent.click(
            await screen.findByRole("button", { name: "Edit Battery watch" }),
        );
        expect(screen.getByLabelText("Rule name")).toHaveValue("Battery watch");
        fireEvent.click(screen.getByLabelText("Rule enabled"));
        fireEvent.click(screen.getByRole("button", { name: "Save rule" }));
        const { id: _id, ...body } = rule;
        void _id;
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/alerts/rules/r1",
                expect.objectContaining({
                    method: "PATCH",
                    body: JSON.stringify({ ...body, enabled: false }),
                }),
            ),
        );
        fireEvent.click(
            screen.getByRole("button", { name: "Delete Battery watch" }),
        );
        expect(screen.getByRole("dialog")).toHaveTextContent(
            "Delete Battery watch?",
        );
        fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith("/api/v1/alerts/rules/r1", {
                method: "DELETE",
            }),
        );
    });
});
