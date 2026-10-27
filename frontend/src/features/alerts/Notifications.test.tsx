import { act, cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { request } from "../../lib/api";
import { fetchFiringAlerts, useAlertNotifications } from "../../lib/alertNotifications";
vi.mock("../../lib/api", () => ({ request: vi.fn() }));
const toast = vi.fn();
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));
const alert = { id: "a1", severity: "critical", device_name: "Samsung", condition: "cpu_high", device_id: "d1" };
afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());
it("fetches all firing pages beyond the first hundred alerts", async () => {
    vi.mocked(request).mockResolvedValueOnce({ items: Array.from({ length: 100 }, (_, i) => ({ ...alert, id: String(i) })), total: 101 });
    vi.mocked(request).mockResolvedValueOnce({ items: [alert], total: 101 });
    const signal = new AbortController().signal;
    expect(await fetchFiringAlerts(signal)).toHaveLength(101);
    expect(request).toHaveBeenLastCalledWith("/api/v1/alerts?state=firing&limit=100&offset=100", { signal });
});
it("suppresses initial events, announces new events once, and survives backend failure", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(request).mockResolvedValue({ items: [alert], total: 1 });
    function Notifications() { useAlertNotifications(); return null; }
    render(<QueryClientProvider client={client}><Notifications /></QueryClientProvider>);
    await waitFor(() => expect(client.getQueryData(["alert-notifications"])).toEqual([alert]));
    expect(toast).not.toHaveBeenCalled();
    vi.mocked(request).mockRejectedValueOnce(new Error("Unavailable"));
    await act(async () => { await client.refetchQueries({ queryKey: ["alert-notifications"] }); });
    expect(toast).not.toHaveBeenCalled();
    const next = { ...alert, id: "a2" };
    vi.mocked(request).mockResolvedValue({ items: [next, alert], total: 2 });
    await act(async () => { await client.refetchQueries({ queryKey: ["alert-notifications"] }); });
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Samsung: cpu high", "error", { title: "Critical alert", href: "/devices/d1" }));
    await act(async () => { await client.refetchQueries({ queryKey: ["alert-notifications"] }); });
    expect(toast).toHaveBeenCalledTimes(1);
});
