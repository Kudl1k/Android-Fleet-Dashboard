import { useContext, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { PollContext } from "./hooks";
import { request } from "./api";
import { useToast } from "./toast";
export interface FiringAlert {
    id: string;
    severity: string;
    device_name: string;
    condition: string;
    device_id: string;
}
type AlertPage = { items: FiringAlert[]; total: number };
export async function fetchFiringAlerts(signal: AbortSignal): Promise<FiringAlert[]> {
    const alerts: FiringAlert[] = [];
    let offset = 0;
    while (true) {
        const page = await request<AlertPage>(
            `/api/v1/alerts?state=firing&limit=100&offset=${offset}`,
            { signal },
        );
        alerts.push(...page.items);
        offset += page.items.length;
        if (page.items.length === 0 || offset >= page.total) break;
    }
    return alerts;
}
/** Firing alerts shared by the shell, notifications and device cards. */
export function useFiringAlerts(interval?: number) {
    const contextPolling = useContext(PollContext);
    const polling = interval ?? contextPolling;
    return useQuery({
        queryKey: ["alert-notifications"],
        queryFn: ({ signal }) => fetchFiringAlerts(signal),
        refetchInterval: polling || false,
    });
}
export function conditionLabel(condition: string) {
    return condition.replaceAll("_", " ");
}
/** Toasts newly firing alerts and returns how many are firing now. */
export function useAlertNotifications(interval?: number) {
    const toast = useToast();
    const seen = useRef<Set<string> | null>(null);
    const query = useFiringAlerts(interval);
    useEffect(() => {
        const alerts = query.data;
        if (!alerts) return;
        if (seen.current === null) {
            seen.current = new Set(alerts.map((a) => a.id));
            return;
        }
        for (const alert of alerts) {
            if (!seen.current.has(alert.id))
                toast(
                    `${alert.device_name}: ${conditionLabel(alert.condition)}`,
                    alert.severity === "critical" ? "error" : "info",
                    {
                        title: `${alert.severity[0]?.toUpperCase()}${alert.severity.slice(1)} alert`,
                        href: `/devices/${encodeURIComponent(alert.device_id)}`,
                    },
                );
        }
        // Only retain current events, so long-running sessions remain bounded.
        seen.current = new Set(alerts.map((alert) => alert.id));
    }, [query.data, toast]);
    return query.data?.length ?? 0;
}
