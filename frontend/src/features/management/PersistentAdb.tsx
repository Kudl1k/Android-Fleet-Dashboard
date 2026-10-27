import Confirmation from "./Confirmation";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export interface PersistenceStatus {
    state:
        | "persistent"
        | "not_installed"
        | "outdated"
        | "switch_required"
        | "root_required"
        | "magisk_required"
        | "offline"
        | "not_applicable";
    connection_type: string;
    message: string;
    installed: boolean;
    server_ip: string | null;
    installed_server_ip: string | null;
    tcp_port_active: boolean;
    key_authorized: boolean | null;
}

/** States where the dashboard can make ADB TCP survive reboots by itself. */
const actionable = new Set(["not_installed", "outdated", "switch_required"]);
const actionLabel: Record<string, string> = {
    not_installed: "Install persistent ADB TCP",
    outdated: "Reinstall persistent ADB TCP",
    switch_required: "Switch to port 5555",
};

/**
 * Checks whether a rooted device re-enables ADB TCP after a reboot, and installs the
 * Magisk boot script when it does not. `banner` renders only when action is needed.
 */
export default function PersistentAdb({
    id,
    connectionType,
    online,
    variant = "panel",
}: {
    id: string;
    connectionType: string;
    online: boolean;
    variant?: "panel" | "banner";
}) {
    const auth = useAuth();
    const client = useQueryClient();
    const admin = ["admin", "administrator"].includes(
        auth.identity?.role ?? "",
    );
    const network = ["wireless_adb", "adb_tcp"].includes(connectionType);
    const path = `/api/v1/devices/${encodeURIComponent(id)}/adb-tcp/persistence`;
    const status = useQuery({
        queryKey: ["adb-persistence", id],
        queryFn: ({ signal }) => request<PersistenceStatus>(path, { signal }),
        enabled: admin && network && online,
        staleTime: 60_000,
        retry: false,
    });
    const [confirm, setConfirm] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    if (!admin || !network) return null;
    const data = status.data;
    const needsAction = !!data && actionable.has(data.state);
    if (variant === "banner" && (!online || !needsAction)) return null;
    const install = async () => {
        setBusy(true);
        setError("");
        try {
            const result = await request<PersistenceStatus>(path, {
                method: "POST",
            });
            client.setQueryData(["adb-persistence", id], result);
            setConfirm(false);
        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : "Persistent ADB TCP installation failed",
            );
        } finally {
            setBusy(false);
            await client.invalidateQueries();
        }
    };
    const action = data && needsAction && (
        <Button
            variant={variant === "banner" ? "default" : "outline"}
            disabled={!online || busy}
            onClick={() => setConfirm(true)}
        >
            {actionLabel[data.state]}
        </Button>
    );
    const dialog = confirm && data && (
        <Confirmation
            title={actionLabel[data.state] ?? "Persistent ADB TCP"}
            onCancel={() => {
                if (!busy) setConfirm(false);
            }}
        >
            <p>
                Installs a Magisk boot script that enables ADB over TCP on port
                5555 after every reboot, independent of Wireless Debugging. A
                firewall on the device admits port 5555 only from this server
                {data.server_ip ? (
                    <>
                        {" "}
                        (<code>{data.server_ip}</code>)
                    </>
                ) : null}
                , and this server's ADB key is authorized so no prompt appears
                on the device.
            </p>
            {data.connection_type === "wireless_adb" && (
                <p>
                    The device then reconnects on port 5555. Open shells and
                    screen sessions will close; its name and history are kept.
                </p>
            )}
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
                    onClick={() => void install()}
                >
                    {busy ? "Installing…" : "Install and reconnect"}
                </Button>
            </div>
        </Confirmation>
    );
    if (variant === "banner")
        return (
            <>
                <Alert className="persistent-adb-banner">
                    <AlertTitle>
                        ADB connection will not survive a reboot
                    </AlertTitle>
                    <AlertDescription>
                        <p>{data?.message}</p>
                        {action}
                    </AlertDescription>
                </Alert>
                {dialog}
            </>
        );
    return (
        <div className="persistent-adb">
            {!online ? (
                <p className="muted">
                    Connect the device to check persistent ADB TCP.
                </p>
            ) : status.isError ? (
                <p className="muted">
                    Persistent ADB TCP check failed: {status.error.message}{" "}
                    <Button
                        variant="link"
                        onClick={() => void status.refetch()}
                    >
                        Check again
                    </Button>
                </p>
            ) : !data ? (
                <p className="muted" role="status">
                    Checking persistent ADB TCP…
                </p>
            ) : (
                <p
                    role="status"
                    className={`persistent-adb-state ${data.state === "persistent" ? "ok" : "attention"}`}
                >
                    <span
                        aria-hidden="true"
                        className={`led ${data.state === "persistent" ? "online" : "degraded"}`}
                    />
                    {data.message}
                </p>
            )}
            {action}
            {error && !confirm && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
            {dialog}
        </div>
    );
}
