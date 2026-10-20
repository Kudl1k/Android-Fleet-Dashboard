import { useContext, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { PollContext } from "../../lib/hooks";
import { useToast } from "../../lib/toast";
import Confirmation from "./Confirmation";
import PairingWizard, { WirelessPortUpdate } from "./PairingWizard";
import AdbTcpSwitch from "./AdbTcpSwitch";
import PairingNetworkSettings from "./PairingNetworkSettings";
import "./management.css";

type Device = {
    id: string;
    name: string;
    host: string | null;
    port: number | null;
    connection_type: string;
    auto_connect: boolean;
    state: string;
    error_code: string | null;
    error_message: string | null;
    retry_in_seconds: number | null;
};
type Draft = {
    name: string;
    host: string;
    port: number;
    auto_connect: boolean;
    connection_type: string;
};
const initial: Draft = {
    name: "",
    host: "",
    port: 5555,
    auto_connect: true,
    connection_type: "wireless_adb",
};

export default function ManagementPage() {
    const { token, can } = useAuth();
    const polling = useContext(PollContext);
    const toast = useToast();
    const client = useQueryClient();
    const devices = useQuery({
        queryKey: ["management-devices"],
        queryFn: ({ signal }) =>
            request<Device[]>("/api/v1/devices", { signal }),
        refetchInterval: polling || false,
    });
    const [draft, setDraft] = useState<Draft>(initial);
    const [editing, setEditing] = useState<Device | null>(null);
    const [removing, setRemoving] = useState<Device | null>(null);
    const mutation = useMutation({
        mutationFn: ({
            path,
            method,
            body,
        }: {
            path: string;
            method: string;
            body?: unknown;
        }) =>
            request<unknown>(path, {
                method,
                ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            }),
        onSuccess: (_, variables) => {
            void client.invalidateQueries();
            const connecting = variables.path.endsWith("/connect");
            toast(connecting ? "Reconnect requested" : "Device configuration updated", "success");
            if (!connecting) {
                setRemoving(null);
                setEditing(null);
                setDraft(initial);
            }
        },
        onError: (error: Error) => toast(error.message, "error"),
    });
    const disabled = !can("device.manage") || mutation.isPending;
    function save(event: FormEvent) {
        event.preventDefault();
        const body =
            editing?.connection_type === "usb"
                ? { name: draft.name, auto_connect: draft.auto_connect }
                : draft;
        mutation.mutate({
            path: `/api/v1/devices${editing ? `/${editing.id}` : ""}`,
            method: editing ? "PATCH" : "POST",
            body,
        });
    }
    return (
        <div className="management-page">
            <div>
                <h1>Device management</h1>
                <p className="muted">
                    Register an authorized ADB connection or update reconnect
                    settings.
                </p>
            </div>
            {!token && (
                <p className="panel">
                    Enter your control token in the navigation to enable
                    management. It stays in memory for this session.
                </p>
            )}
            <PairingWizard />
            <PairingNetworkSettings />
            <section className="panel">
                <h2>{editing ? `Edit ${editing.name}` : "Register device"}</h2>
                <form onSubmit={save} className="grid">
                    <label className="field">
                        Device name
                        <input
                            required
                            maxLength={128}
                            value={draft.name}
                            onChange={(e) =>
                                setDraft({ ...draft, name: e.target.value })
                            }
                        />
                    </label>
                    {editing?.connection_type !== "usb" && (
                        <>
                            <label className="field">
                                Connection type
                                <select
                                    value={draft.connection_type}
                                    onChange={(e) =>
                                        setDraft({
                                            ...draft,
                                            connection_type: e.target.value,
                                        })
                                    }
                                >
                                    <option value="wireless_adb">
                                        Wireless debugging
                                    </option>
                                    <option value="adb_tcp">ADB TCP</option>
                                </select>
                            </label>
                            <label className="field">
                                IP address or hostname
                                <input
                                    required
                                    value={draft.host}
                                    onChange={(e) =>
                                        setDraft({
                                            ...draft,
                                            host: e.target.value,
                                        })
                                    }
                                    placeholder="192.168.1.100"
                                />
                            </label>
                            <label className="field">
                                ADB connection port
                                <input
                                    type="number"
                                    required
                                    min={1}
                                    max={65535}
                                    value={draft.port}
                                    onChange={(e) =>
                                        setDraft({
                                            ...draft,
                                            port: Number(e.target.value),
                                        })
                                    }
                                />
                            </label>
                        </>
                    )}
                    <label>
                        <input
                            type="checkbox"
                            checked={draft.auto_connect}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    auto_connect: e.target.checked,
                                })
                            }
                        />{" "}
                        Automatically reconnect
                    </label>
                    <p className="muted">
                        Use the connection port, not the pairing port. Pairing
                        and authorization are performed through the container
                        ADB server.
                    </p>
                    <div>
                        <button className="button" disabled={disabled}>
                            {mutation.isPending
                                ? "Saving…"
                                : editing
                                  ? "Save changes"
                                  : "Register device"}
                        </button>
                        {editing && (
                            <button
                                type="button"
                                className="button"
                                onClick={() => {
                                    setEditing(null);
                                    setDraft(initial);
                                }}
                            >
                                Cancel edit
                            </button>
                        )}
                    </div>
                </form>
            </section>
            <section className="panel">
                <h2>Registered connections</h2>
                {devices.isPending && (
                    <p role="status" className="skeleton">
                        Loading connections…
                    </p>
                )}
                {devices.isError && (
                    <p role="alert" className="error">
                        {devices.error.message}{" "}
                        <button
                            className="button"
                            onClick={() => void devices.refetch()}
                        >
                            Retry
                        </button>
                    </p>
                )}
                {devices.data?.length === 0 && (
                    <p>No registered devices. Add a connection above.</p>
                )}
                <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Device</th>
                                <th>Connection</th>
                                <th>Reconnect</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {devices.data?.map((device) => (
                                <tr key={device.id}>
                                    <td>
                                        <Link to={`/devices/${device.id}`}>
                                            {device.name}
                                        </Link>
                                        <div className="muted">
                                            {device.state}
                                        </div>
                                        {device.error_code && (
                                            <details>
                                                <summary>
                                                    Connection troubleshooting
                                                </summary>
                                                <p>
                                                    {device.error_code}:{" "}
                                                    {device.error_message ||
                                                        "Connection unavailable"}
                                                </p>
                                                <p>
                                                    Check that Wireless
                                                    Debugging is enabled, both
                                                    hosts share a reachable
                                                    network, and the connection
                                                    port is current.
                                                </p>
                                                {device.retry_in_seconds !==
                                                    null && (
                                                    <p>
                                                        Next retry in{" "}
                                                        {Math.ceil(
                                                            device.retry_in_seconds,
                                                        )}{" "}
                                                        seconds.
                                                    </p>
                                                )}
                                            </details>
                                        )}
                                    </td>
                                    <td>
                                        {device.host
                                            ? `${device.host}:${device.port ?? "unavailable"}`
                                            : "USB"}
                                    </td>
                                    <td>
                                        {device.auto_connect
                                            ? "Enabled"
                                            : "Disabled"}
                                    </td>
                                    <td>
                                        {can("device.manage") && device.connection_type === "wireless_adb" && device.host && <WirelessPortUpdate id={device.id} host={device.host} port={device.port} />}
                                        {device.connection_type === "wireless_adb" && <AdbTcpSwitch id={device.id} online={device.state === "online"} />}
                                        <button
                                            className="button"
                                            disabled={disabled}
                                            onClick={() => {
                                                setEditing(device);
                                                setDraft({
                                                    name: device.name,
                                                    host: device.host ?? "",
                                                    port: device.port ?? 5555,
                                                    connection_type:
                                                        device.connection_type,
                                                    auto_connect:
                                                        device.auto_connect,
                                                });
                                            }}
                                            aria-label={`Edit ${device.name}`}
                                        >
                                            Edit
                                        </button>
                                        <button
                                            className="button"
                                            disabled={disabled}
                                            onClick={() =>
                                                mutation.mutate({
                                                    path: `/api/v1/devices/${device.id}/connect`,
                                                    method: "POST",
                                                })
                                            }
                                            aria-label={`Reconnect ${device.name}`}
                                        >
                                            Reconnect
                                        </button>
                                        <button
                                            className="button"
                                            disabled={disabled}
                                            onClick={() => setRemoving(device)}
                                            aria-label={`Remove ${device.name}`}
                                        >
                                            Remove
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </section>
            {removing && (
                <Confirmation
                    title={`Remove ${removing.name}?`}
                    onCancel={() => setRemoving(null)}
                >
                    <p>
                        This removes its registration. The device itself is not
                        modified.
                    </p>
                    <button
                        className="button"
                        disabled={disabled}
                        onClick={() =>
                            mutation.mutate({
                                path: `/api/v1/devices/${removing.id}`,
                                method: "DELETE",
                            })
                        }
                    >
                        Confirm removal
                    </button>
                    <button
                        className="button"
                        onClick={() => setRemoving(null)}
                    >
                        Cancel
                    </button>
                </Confirmation>
            )}
        </div>
    );
}
