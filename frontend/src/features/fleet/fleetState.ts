import type { Device } from "../../lib/api";
export function fleetGroup(device: Device): string {
    if (device.state === "online") return "online";
    return ["offline", "disconnected"].includes(device.state)
        ? "offline"
        : "degraded";
}
