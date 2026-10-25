import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./api";
import { useAuth } from "./auth";

export interface RuntimeSetting {
    key: string;
    label: string;
    description: string;
    minimum: number;
    maximum: number;
    default: number;
    value: number;
    overridden: boolean;
    per_device: boolean;
}
export interface SettingsResponse {
    settings: RuntimeSetting[];
    devices: Record<string, Record<string, number>>;
}

export function useRuntimeSettings() {
    const auth = useAuth();
    return useQuery({
        queryKey: ["runtime-settings"],
        queryFn: ({ signal }) => request<SettingsResponse>("/api/v1/settings", { signal }),
        enabled: auth.can("device.read"),
    });
}

/** Saves fleet-wide values, or one device's overrides when `deviceId` is given. null resets. */
export function useSaveSettings(deviceId?: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (values: Record<string, number | null>) =>
            request<SettingsResponse>(
                deviceId ? `/api/v1/settings/devices/${encodeURIComponent(deviceId)}` : "/api/v1/settings",
                { method: "PUT", body: JSON.stringify({ values }) },
            ),
        onSuccess: (data) => client.setQueryData(["runtime-settings"], data),
    });
}

export function formatSeconds(seconds: number) {
    if (seconds < 60) return `${seconds} s`;
    if (seconds % 3600 === 0) return `${seconds / 3600} h`;
    if (seconds % 60 === 0) return `${seconds / 60} min`;
    return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}
