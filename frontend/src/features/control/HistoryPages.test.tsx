import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPage from "./OperationsPage";
import AuditPage from "./AuditPage";
import { request } from "../../lib/api";
import type { Operation } from "./operations";
const auth = { identity: { identity: "operator-a", role: "operator", permissions: [] as string[] }, can: (permission: string) => auth.identity.permissions.includes(permission) };
vi.mock("../../lib/auth", () => ({ useAuth: () => auth }));
vi.mock("../../lib/api", () => ({ request: vi.fn() }));
const operation = (id: string, actor: string, overrides: Partial<Operation> = {}): Operation => ({id, actor, role: "operator", device_id: "device-one", action: "apps.list", state: "running", created_at: 1791576000, started_at: 1791576001, finished_at: null, duration: null, result: null, error: null, cancellable: true, ...overrides});
function show(node: React.ReactNode) { render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})}>{node}</QueryClientProvider>); }
beforeEach(() => {vi.clearAllMocks(); auth.identity.role = "operator"; auth.identity.permissions = ["operations.read", "operations.cancel"];});
describe("operation history authorization", () => {
    it("offers operators cancellation only for their own active cancellable operations", async () => {
        vi.mocked(request).mockResolvedValue({items: [operation("own", "operator-a"), operation("other", "operator-b"), operation("terminal", "operator-a", {state: "succeeded"}), operation("unsafe", "operator-a", {cancellable: false})], total: 4});
        show(<OperationsPage/>);
        const button = await screen.findByRole("button", {name: "Cancel operation"});
        expect(screen.getAllByRole("button", {name: "Cancel operation"})).toHaveLength(1);
        expect(within(button.closest("tr")!).getByText("own")).toBeInTheDocument();
        fireEvent.click(button);
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/operations/own/cancel", {method: "POST"}));
    });
    it("permits administrators to cancel another actor's operation", async () => {
        auth.identity.role = "administrator";
        vi.mocked(request).mockResolvedValue({items: [operation("other", "operator-b")], total: 1});
        show(<OperationsPage/>);
        fireEvent.click(await screen.findByRole("button", {name: "Cancel operation"}));
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/operations/other/cancel", {method: "POST"}));
    });
    it("withholds cancellation without its operation permission and displays sanitized failures", async () => {
        auth.identity.permissions = ["operations.read"];
        vi.mocked(request).mockResolvedValue({items: [operation("own", "operator-a", {error: "Android rejected the action"})], total: 1});
        show(<OperationsPage/>);
        expect(await screen.findByText("Android rejected the action")).toBeInTheDocument();
        expect(screen.queryByRole("button", {name: "Cancel operation"})).not.toBeInTheDocument();
    });
    it("passes fleet action and outcome filters and resets pagination", async () => {
        vi.mocked(request).mockResolvedValue({items: [operation("own", "operator-a")], total: 70});
        show(<OperationsPage/>);
        await screen.findByText("own");
        fireEvent.click(screen.getByRole("button", {name: "Next"}));
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/operations?limit=50&offset=50", expect.anything()));
        fireEvent.change(screen.getByLabelText("Device ID"), {target: {value: "device-one"}});
        fireEvent.change(screen.getByLabelText("Action"), {target: {value: "screenshot"}});
        fireEvent.change(screen.getByLabelText("Outcome"), {target: {value: "failed"}});
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/operations?limit=50&offset=0&device_id=device-one&action=screenshot&state=failed", expect.anything()));
    });
});
describe("audit history authorization and pagination", () => {
    it("does not fetch audit records without audit permission", () => {
        show(<AuditPage/>);
        expect(screen.getByText("Administrator audit access is required.")).toBeInTheDocument();
        expect(request).not.toHaveBeenCalled();
    });
    it("renders audit fields, advances pages, and resets offset when filtering", async () => {
        auth.identity.permissions = ["audit.read"];
        vi.mocked(request).mockResolvedValue({items: [{id: 1, timestamp: 1791576000, actor: "operator-b", role: "operator", device_id: "device-one", action: "apps.stop", request_id: "request-one", authorization: "allowed", outcome: "failed", duration: 2.25, error: "Android rejected the action"}], total: 70});
        show(<AuditPage/>);
        expect(await screen.findByText("Android rejected the action", {exact: false})).toBeInTheDocument();
        expect(screen.getByText("request-one")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", {name: "Next"}));
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/audit?limit=50&offset=50", expect.anything()));
        fireEvent.change(screen.getByLabelText("actor"), {target: {value: "operator-b"}});
        fireEvent.change(screen.getByLabelText("authorization"), {target: {value: "denied"}});
        await waitFor(() => expect(request).toHaveBeenCalledWith("/api/v1/audit?limit=50&offset=0&actor=operator-b&authorization=denied", expect.anything()));
        expect(screen.getByRole("button", {name: "Previous"})).toBeDisabled();
    });
    it("reports audit fetch failure without inventing history", async () => {
        auth.identity.permissions = ["audit.read"];
        vi.mocked(request).mockRejectedValue(new Error("Audit database unavailable"));
        show(<AuditPage/>);
        expect(await screen.findByRole("alert")).toHaveTextContent("Audit database unavailable");
        expect(screen.queryByText("No audit entries match these filters.")).not.toBeInTheDocument();
    });
});
