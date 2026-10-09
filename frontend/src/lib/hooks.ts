import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { request, type Device, type CurrentMetrics, type History } from "./api";
export const PollContext = createContext(15000);
export function useDevices() {
    const polling = useContext(PollContext);
    return useQuery({
        queryKey: ["devices"],
        queryFn: ({ signal }) =>
            request<Device[]>("/api/v1/devices", { signal }),
        refetchInterval: polling || false,
    });
}
export function useDevice(id: string) {
    const polling = useContext(PollContext);
    return useQuery({
        queryKey: ["device", id],
        queryFn: ({ signal }) =>
            request<Device>(`/api/v1/devices/${encodeURIComponent(id)}`, {
                signal,
            }),
        refetchInterval: polling || false,
    });
}
export function useMetrics(id: string) {
    const polling = useContext(PollContext);
    return useQuery({
        queryKey: ["metrics", id],
        queryFn: ({ signal }) =>
            request<CurrentMetrics>(
                `/api/v1/devices/${encodeURIComponent(id)}/metrics`,
                { signal },
            ),
        refetchInterval: polling || false,
    });
}
export function useHistory(id: string, minutes: number, metric: string) {
    const polling = useContext(PollContext);
    return useQuery({
        queryKey: ["history", id, minutes, metric],
        queryFn: async ({ signal }) => {
            const end = new Date();
            const start = new Date(end.getTime() - minutes * 60000);
            const params = new URLSearchParams({
                start: start.toISOString(),
                end: end.toISOString(),
                metric,
                limit: "10000",
            });
            let cursor: string | null = null;
            const points: History["points"] = [];
            let pages = 0;
            do {
                if (cursor) params.set("cursor", cursor);
                const page = await request<History>(
                    `/api/v1/devices/${encodeURIComponent(id)}/metrics/history?${params}`,
                    { signal },
                );
                points.push(...page.points);
                cursor = page.next_cursor;
                pages++;
            } while (cursor && pages < 20);
            return { points, truncated: cursor !== null };
        },
        refetchInterval: polling ? Math.max(polling, 60000) : false,
    });
}
