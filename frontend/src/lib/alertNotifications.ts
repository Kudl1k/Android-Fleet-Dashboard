import { useContext, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { PollContext } from "./hooks";
import { request } from "./api";
import { useToast } from "./toast";
interface Alert {
    id: string;
    severity: string;
    device_name: string;
    condition: string;
    device_id: string;
}
type AlertPage = { items: Alert[]; total: number };
export async function fetchFiringAlerts(signal: AbortSignal): Promise<Alert[]> {
    const alerts: Alert[] = [];
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
export function useAlertNotifications() {
    const polling = useContext(PollContext);
    const toast = useToast();
    const seen = useRef<Set<string> | null>(null);
    const query = useQuery({
        queryKey: ["alert-notifications"],
        queryFn: ({ signal }) => fetchFiringAlerts(signal),
        refetchInterval: polling || false,
    });
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
                    `${alert.severity.toUpperCase()}: ${alert.device_name}: ${alert.condition.replaceAll("_", " ")}`,
                    "info",
                );
        }
        // Only retain current events, so long-running sessions remain bounded.
        seen.current = new Set(alerts.map((alert) => alert.id));
    }, [query.data, toast]);
}
