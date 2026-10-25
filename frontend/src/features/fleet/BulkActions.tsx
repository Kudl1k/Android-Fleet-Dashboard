import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Camera, Lock, Power, Sun, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import Confirmation from "../management/Confirmation";
import { request, type Device } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "../../lib/toast";
import { operationPermission } from "../control/operations";

export const bulkActions = [
    { action: "screen.wake", label: "Wake screen", icon: Sun },
    { action: "screen.lock", label: "Lock screen", icon: Lock },
    { action: "screenshot", label: "Screenshot", icon: Camera },
    { action: "reboot", label: "Reboot", icon: Power },
] as const;

export function useBulkAllowed() {
    const auth = useAuth();
    return bulkActions.filter(({ action }) => auth.can(operationPermission(action)));
}

/** Queues one operation per selected device; each device still runs and audits it separately. */
export default function BulkActions({
    devices,
    onClear,
}: {
    devices: Device[];
    onClear: () => void;
}) {
    const allowed = useBulkAllowed();
    const toast = useToast();
    const client = useQueryClient();
    const [pending, setPending] = useState<string | null>(null);
    const [confirming, setConfirming] = useState(false);
    async function run(action: string, label: string) {
        setPending(action);
        const results = await Promise.allSettled(
            devices.map((device) =>
                request(`/api/v1/devices/${encodeURIComponent(device.id)}/operations`, {
                    method: "POST",
                    body: JSON.stringify({ action, ...(action === "reboot" && { confirmed: true }) }),
                }),
            ),
        );
        setPending(null);
        setConfirming(false);
        await client.invalidateQueries({ queryKey: ["operations"] });
        const failed = results.flatMap((result, index) =>
            result.status === "rejected" ? [devices[index].name] : [],
        );
        if (failed.length)
            toast(`${failed.join(", ")} could not be queued.`, "error", {
                title: `${label}: ${devices.length - failed.length} of ${devices.length} queued`,
                href: "/operations",
            });
        else
            toast(`Queued on ${devices.length} ${devices.length === 1 ? "device" : "devices"}.`, "success", {
                title: label,
                href: "/operations",
            });
    }
    return (
        <div className="bulk-bar" role="region" aria-label="Bulk actions">
            <strong>{devices.length} selected</strong>
            <div className="bulk-actions">
                {allowed.map(({ action, label, icon: Icon }) => (
                    <Button
                        key={action}
                        variant={action === "reboot" ? "destructive" : "outline"}
                        disabled={!devices.length || pending !== null}
                        aria-busy={pending === action}
                        onClick={() => (action === "reboot" ? setConfirming(true) : void run(action, label))}
                    >
                        <Icon data-icon="inline-start" aria-hidden="true" />
                        {pending === action ? "Queuing…" : label}
                    </Button>
                ))}
                <Button variant="ghost" onClick={onClear} disabled={pending !== null}>
                    <X data-icon="inline-start" aria-hidden="true" />
                    Done
                </Button>
            </div>
            {confirming && (
                <Confirmation
                    title={`Reboot ${devices.length} ${devices.length === 1 ? "device" : "devices"}?`}
                    onCancel={() => pending === null && setConfirming(false)}
                >
                    <p>{devices.map((device) => device.name).join(", ")} will restart and drop their ADB sessions.</p>
                    <div className="actions device-dialog-actions">
                        <Button variant="outline" disabled={pending !== null} onClick={() => setConfirming(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            disabled={pending !== null}
                            aria-busy={pending === "reboot"}
                            onClick={() => void run("reboot", "Reboot")}
                        >
                            {pending === "reboot" ? "Queuing…" : "Reboot devices"}
                        </Button>
                    </div>
                </Confirmation>
            )}
        </div>
    );
}
