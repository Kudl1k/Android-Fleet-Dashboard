import Confirmation from "./Confirmation";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function AdbTcpSwitch({
    id,
    online,
}: {
    id: string;
    online: boolean;
}) {
    const auth = useAuth();
    const client = useQueryClient();
    const [confirm, setConfirm] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [done, setDone] = useState(false);
    if (!["admin", "administrator"].includes(auth.identity?.role ?? ""))
        return null;
    const run = async () => {
        setBusy(true);
        setError("");
        try {
            await request(`/api/v1/devices/${id}/adb-tcp`, { method: "POST" });
            setDone(true);
            setConfirm(false);
        } catch (err) {
            setError(err instanceof Error ? err.message : "TCP switch failed");
        } finally {
            setBusy(false);
            await client.invalidateQueries();
        }
    };
    return (
        <div className="device-tcp-switch">
            {done ? (
                <p role="status">ADB TCP enabled on port 5555.</p>
            ) : (
                <Button
                    variant="outline"
                    disabled={!online || busy}
                    onClick={() => setConfirm(true)}
                >
                    Switch to ADB TCP
                </Button>
            )}
            {confirm && (
                <Confirmation
                    title="Switch to ADB TCP"
                    onCancel={() => {
                        if (!busy) setConfirm(false);
                    }}
                >
                    <p>
                        Switch this device to ADB TCP on port 5555? This may
                        close open shells. Its name and history are preserved.
                        Use a trusted network; TCP mode may need enabling again
                        after reboot.
                    </p>
                    {error && (
                        <p role="alert" className="error">
                            {error}
                        </p>
                    )}
                    <div className="actions device-dialog-actions">
                        <Button
                            variant="outline"
                            disabled={busy}
                            onClick={() => setConfirm(false)}
                        >
                            Cancel
                        </Button>
                        <Button
                            className="device-pending-action"
                            aria-busy={busy}
                            disabled={busy}
                            onClick={() => void run()}
                        >
                            {busy ? "Switching…" : "Enable TCP and reconnect"}
                        </Button>
                    </div>
                </Confirmation>
            )}
            {error && !confirm && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
        </div>
    );
}
