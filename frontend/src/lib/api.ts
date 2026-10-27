export interface Device {
    id: string;
    serial: string;
    name: string;
    state: string;
    connection_type: string;
    manufacturer: string | null;
    model: string | null;
    android_version: string | null;
    root_available: boolean | null;
    capabilities: string[];
    last_seen: string | null;
    host: string | null;
    port: number | null;
    auto_connect: boolean;
    error_code: string | null;
    error_message: string | null;
    retry_in_seconds: number | null;
    mdns_service?: string | null;
    metadata?: Record<string, string>;
}
export interface Metric {
    name: string;
    value: number;
    unit: string;
    kind: string;
    labels: Record<string, string>;
}
export interface CurrentMetrics {
    device_id: string;
    state: string;
    observed_at: string | null;
    stale: boolean;
    values: Metric[];
}
export interface HistoryPoint extends Metric {
    observed_at: string;
}
export interface History {
    points: HistoryPoint[];
    next_cursor: string | null;
}
const TOKEN_KEY = "fleet-control-token";
function storedToken() {
    try {
        return localStorage.getItem(TOKEN_KEY) ?? "";
    } catch {
        return "";
    }
}
function storeToken(token: string) {
    try {
        if (token) localStorage.setItem(TOKEN_KEY, token);
        else localStorage.removeItem(TOKEN_KEY);
    } catch {
        // Storage can be blocked; the token then lasts until the page reloads.
    }
}
let controlToken = storedToken();
/** The signed-in token, kept across reloads until sign-out or rejection. */
export function getControlToken() {
    return controlToken;
}
export function setControlToken(token: string) {
    controlToken = token;
    storeToken(token);
}
export const AUTH_EXPIRED_EVENT = "fleet-auth-expired";
/** Asks the shell to open its access dialog, e.g. from a page that needs sign-in. */
export const OPEN_ACCESS_EVENT = "fleet-open-access";
export function isAccessError(error: unknown) {
    return error instanceof ApiError && (error.status === 401 || error.status === 403);
}
function expireCredential(token: string, status: number) {
    if (status === 401 && token && token === controlToken) {
        setControlToken("");
        window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
}
export class ApiError extends Error {
    constructor(
        public status: number,
        message: string,
    ) {
        super(message);
    }
}
export async function request<T>(
    path: string,
    options: RequestInit = {},
): Promise<T> {
    const token = controlToken;
    const headers = new Headers(options.headers);
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (controlToken) headers.set("Authorization", `Bearer ${controlToken}`);
    let response: Response;
    try {
        response = await fetch(path, {
            ...options,
            headers,
            credentials: "omit",
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError")
            throw error;
        throw new ApiError(
            0,
            "Backend unavailable. Check the manager connection and try again.",
        );
    }
    if (!response.ok) {
        expireCredential(token, response.status);
        const body = await response.json().catch(() => null);
        throw new ApiError(
            response.status,
            body?.error?.message ??
                (typeof body?.detail === "string" ? body.detail : undefined) ??
                (response.status === 401
                    ? "A valid control token is required."
                    : `Request failed (${response.status}).`),
        );
    }
    const result = response.status === 204 ? undefined : await response.json();
    if (token !== controlToken) throw new ApiError(401, "Access changed. Retry the request.");
    return result as T;
}
export function metricValue(
    metrics: CurrentMetrics | undefined,
    name: string,
): number | null {
    return metrics && !metrics.stale && metrics.state === "online"
        ? (metrics.values.find((m) => m.name === name)?.value ?? null)
        : null;
}
export function formatMetric(value: number | null, unit: string): string {
    if (value === null) return "Unavailable";
    if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
    if (unit === "bytes") {
        const units = ["B", "KiB", "MiB", "GiB", "TiB"];
        let i = 0;
        while (value >= 1024 && i < 4) {
            value /= 1024;
            i++;
        }
        return `${value.toFixed(1)} ${units[i]}`;
    }
    if (unit === "hertz") return `${(value / 1e6).toFixed(0)} MHz`;
    if (unit === "seconds")
        return `${Math.floor(value / 86400)}d ${Math.floor((value % 86400) / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
    return `${value.toFixed(1)} ${unit === "celsius" ? "°C" : unit}`;
}

export async function protectedImage(path: string): Promise<Blob> {
    const token = controlToken;
    const headers = new Headers();
    if (controlToken) headers.set("Authorization", `Bearer ${controlToken}`);
    const response = await fetch(path, { headers, credentials: "omit" });
    if (!response.ok) {
        expireCredential(token, response.status);
        throw new ApiError(response.status, "Screenshot unavailable or access denied.");
    }
    const blob = await response.blob();
    if (token !== controlToken) throw new ApiError(401, "Access changed. Request the screenshot again.");
    return blob;
}
