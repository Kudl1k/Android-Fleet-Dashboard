import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useHistory } from "./hooks";
describe("history API hook", () => {
    it("follows cursors with a fixed query range", async () => {
        const fetch = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        points: [
                            {
                                name: "cpu_usage",
                                value: 0.1,
                                unit: "ratio",
                                labels: {},
                                observed_at: "2026-01-01",
                            },
                        ],
                        next_cursor: "second",
                    }),
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ points: [], next_cursor: null })),
            );
        vi.stubGlobal("fetch", fetch);
        const client = new QueryClient({
            defaultOptions: { queries: { retry: false } },
        });
        const wrapper = ({ children }: { children: ReactNode }) => (
            <QueryClientProvider client={client}>
                {children}
            </QueryClientProvider>
        );
        const { result } = renderHook(() => useHistory("a", 60, "cpu_usage"), {
            wrapper,
        });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(fetch).toHaveBeenCalledTimes(2);
        const first = new URL(fetch.mock.calls[0][0], "http://localhost");
        const second = new URL(fetch.mock.calls[1][0], "http://localhost");
        expect(second.searchParams.get("cursor")).toBe("second");
        expect(second.searchParams.get("start")).toBe(
            first.searchParams.get("start"),
        );
        expect(result.current.data?.truncated).toBe(false);
    });
});

it("refreshes device history at most once a minute", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const mounted = renderHook(() => useHistory("phone", 60, "cpu_core_usage"), { wrapper });
    expect(client.getQueryCache().find({ queryKey: ["history", "phone", 60, "cpu_core_usage"] })?.options).toMatchObject({ refetchInterval: 60000 });
    mounted.unmount();
    client.clear();
});
