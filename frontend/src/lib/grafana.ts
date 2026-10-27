/** Grafana is published beside the dashboard (port 1900 in Compose); override at build time. */
export function grafanaBase(): string {
    const configured = (import.meta as unknown as { env?: Record<string, string | undefined> }).env
        ?.VITE_GRAFANA_URL;
    return (configured || `${window.location.protocol}//${window.location.hostname}:1900`).replace(/\/$/, "");
}

export function grafanaDeviceUrl(deviceId: string): string {
    return `${grafanaBase()}/d/android-fleet-device?var-device=${encodeURIComponent(deviceId)}`;
}
