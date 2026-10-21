import { useContext, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { PollContext } from "../../lib/hooks";
import { useToast } from "../../lib/toast";
import Confirmation from "../management/Confirmation";
import "../management/management.css";

type Condition =
    | "battery_low"
    | "battery_temperature"
    | "device_temperature"
    | "cpu_high"
    | "memory_high"
    | "storage_low"
    | "offline"
    | "telemetry_stale";
type Severity = "info" | "warning" | "critical";
type Rule = {
    id: string;
    name: string;
    condition: Condition;
    device_id: string | null;
    severity: Severity;
    threshold: number;
    duration_seconds: number;
    hysteresis: number;
    enabled: boolean;
};
type Event = {
    id: string;
    rule_id: string;
    device_id: string;
    device_name: string;
    condition: Condition;
    severity: Severity;
    threshold: number;
    value: number | null;
    state: string;
    started_at: string;
    fired_at: string | null;
    updated_at: string;
};
type Page = { items: Event[]; total: number; limit: number; offset: number };
const labels: Record<Condition, string> = {
    battery_low: "Low battery",
    battery_temperature: "High battery temperature",
    device_temperature: "High device temperature",
    cpu_high: "High CPU",
    memory_high: "High memory",
    storage_low: "Low free storage",
    offline: "Device offline",
    telemetry_stale: "Stale or missing telemetry",
};
const initial: Omit<Rule, "id"> = {
    name: "",
    condition: "battery_low",
    device_id: null,
    severity: "warning",
    threshold: 0.2,
    duration_seconds: 60,
    hysteresis: 0.05,
    enabled: true,
};
function unit(condition: Condition) {
    return ["offline", "telemetry_stale"].includes(condition)
        ? "seconds"
        : condition.includes("temperature")
          ? "°C"
          : "ratio (0–1)";
}

export default function AlertsPage() {
    const { token, can } = useAuth();
    const polling = useContext(PollContext);
    const toast = useToast();
    const client = useQueryClient();
    const [severity, setSeverity] = useState("");
    const [state, setState] = useState("firing");
    const [device, setDevice] = useState("");
    const [offset, setOffset] = useState(0);
    const [editing, setEditing] = useState<Rule | null>(null);
    const [removing, setRemoving] = useState<Rule | null>(null);
    const [draft, setDraft] = useState(initial);
    const devices = useQuery({
        queryKey: ["alert-devices"],
        queryFn: ({ signal }) =>
            request<{ id: string; name: string }[]>("/api/v1/devices", {
                signal,
            }),
    });
    const rules = useQuery({
        queryKey: ["alert-rules"],
        queryFn: ({ signal }) =>
            request<Rule[]>("/api/v1/alerts/rules", { signal }),
    });
    const active = useQuery({
        queryKey: ["active-alerts-summary"],
        queryFn: async ({ signal }) => {
            const states = ["pending", "firing", "acknowledged"];
            const levels = ["critical", "warning", "info"];
            const totals = await Promise.all(
                levels.map(async (severity) => {
                    const pages = await Promise.all(
                        states.map((state) =>
                            request<Page>(
                                `/api/v1/alerts?state=${state}&severity=${severity}&limit=1&offset=0`,
                                { signal },
                            ),
                        ),
                    );
                    return pages.reduce((sum, page) => sum + page.total, 0);
                }),
            );
            return {
                critical: totals[0],
                warning: totals[1],
                info: totals[2],
                total: totals.reduce((a, b) => a + b, 0),
            };
        },
        refetchInterval: polling || false,
    });
    const query = new URLSearchParams({
        limit: "50",
        offset: String(offset),
        ...(state ? { state } : {}),
        ...(severity ? { severity } : {}),
        ...(device ? { device_id: device } : {}),
    });
    const events = useQuery({
        queryKey: ["alert-events", state, severity, device, offset],
        queryFn: ({ signal }) =>
            request<Page>(`/api/v1/alerts?${query}`, { signal }),
        refetchInterval: polling || false,
    });
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
            const isRule = variables.path.includes("/rules");
            toast(isRule ? "Alert configuration updated" : "Alert acknowledged", "success");
            if (isRule) {
                setEditing(null);
                setRemoving(null);
                setDraft(initial);
            }
        },
        onError: (error: Error) => toast(error.message, "error"),
    });
    const disabled = !can("alerts.manage") || mutation.isPending;
    function save(event: FormEvent) {
        event.preventDefault();
        mutation.mutate({
            path: `/api/v1/alerts/rules${editing ? `/${editing.id}` : ""}`,
            method: editing ? "PATCH" : "POST",
            body: draft,
        });
    }
    return (
        <div className="alerts-page">
            <div>
                <h1>Alerts</h1>
                <p className="muted">
                    Server evaluated rules continue running when this dashboard
                    is closed.
                </p>
            </div>
            <div className="panel">
                <strong>
                    {active.data ? active.data.total : "Unavailable"} active
                    alerts
                </strong>
                <p>
                    {(["critical", "warning", "info"] as const).map((level) => (
                        <span className="badge" key={level}>
                            {level}:{" "}
                            {active.data
                                ? active.data[level]
                                : "unavailable"}{" "}
                        </span>
                    ))}
                </p>
                <p className="muted">
                    Active includes pending, firing, and acknowledged alerts.
                </p>
                {active.isError && (
                    <p role="alert">
                        Alert summary unavailable: {active.error.message}
                    </p>
                )}
            </div>
            <section className="panel">
                <h2>Alert activity and history</h2>
                <div className="grid">
                    <label className="field">
                        Severity
                        <select
                            value={severity}
                            onChange={(e) => {
                                setSeverity(e.target.value);
                                setOffset(0);
                            }}
                        >
                            <option value="">All severities</option>
                            <option>critical</option>
                            <option>warning</option>
                            <option>info</option>
                        </select>
                    </label>
                    <label className="field">
                        State
                        <select
                            value={state}
                            onChange={(e) => {
                                setState(e.target.value);
                                setOffset(0);
                            }}
                        >
                            <option value="">All states / history</option>
                            <option>firing</option>
                            <option>pending</option>
                            <option>acknowledged</option>
                            <option>resolved</option>
                        </select>
                    </label>
                    <label className="field">
                        Device
                        <select
                            value={device}
                            onChange={(e) => {
                                setDevice(e.target.value);
                                setOffset(0);
                            }}
                        >
                            <option value="">All devices</option>
                            {devices.data?.map((item) => (
                                <option key={item.id} value={item.id}>
                                    {item.name}
                                </option>
                            ))}
                        </select>
                    </label>
                </div>
                {events.isPending && (
                    <p role="status" className="skeleton">
                        Loading alerts…
                    </p>
                )}
                {events.isError && (
                    <p role="alert" className="error">
                        {events.error.message}
                        <button
                            className="button"
                            onClick={() => void events.refetch()}
                        >
                            Retry
                        </button>
                    </p>
                )}
                {events.data?.items.length === 0 && (
                    <p>No alerts match these filters.</p>
                )}
                <div className="table-wrap" tabIndex={0} role="region" aria-label="Alert activity">
                    <table>
                        <thead>
                            <tr>
                                <th>Device / condition</th>
                                <th>Severity</th>
                                <th>Threshold / observed</th>
                                <th>State / timestamp</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events.data?.items.map((event) => (
                                <tr key={event.id}>
                                    <td>
                                        <Link
                                            to={`/devices/${event.device_id}`}
                                        >
                                            {event.device_name}
                                        </Link>
                                        <div>{labels[event.condition]}</div>
                                    </td>
                                    <td>{event.severity}</td>
                                    <td>
                                        {event.threshold}{" "}
                                        {unit(event.condition)}
                                        <div className="muted">
                                            Observed:{" "}
                                            {event.value ?? "Unavailable"}
                                        </div>
                                    </td>
                                    <td>
                                        {event.state}
                                        <div className="muted">
                                            {new Date(
                                                event.fired_at ??
                                                    event.started_at,
                                            ).toLocaleString()}
                                        </div>
                                    </td>
                                    <td>
                                        {event.state === "firing" && (
                                            <button
                                                className="button"
                                                disabled={disabled}
                                                onClick={() =>
                                                    mutation.mutate({
                                                        path: `/api/v1/alerts/${event.id}/acknowledge`,
                                                        method: "POST",
                                                    })
                                                }
                                                aria-label={`Acknowledge ${event.device_name} ${labels[event.condition]}`}
                                            >
                                                Acknowledge
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {events.data && (
                    <div>
                        <button
                            className="button"
                            disabled={offset === 0}
                            onClick={() => setOffset(Math.max(0, offset - 50))}
                        >
                            Previous
                        </button>
                        <span>
                            {" "}
                            {events.data.total === 0 ? 0 : offset + 1}–
                            {Math.min(offset + 50, events.data.total)} of{" "}
                            {events.data.total}{" "}
                        </span>
                        <button
                            className="button"
                            disabled={offset + 50 >= events.data.total}
                            onClick={() => setOffset(offset + 50)}
                        >
                            Next
                        </button>
                    </div>
                )}
            </section>
            <section className="panel">
                <h2>Alert rules</h2>
                {!token && (
                    <p>
                        Enter your control token to configure rules or
                        acknowledge alerts.
                    </p>
                )}
                <p className="muted">
                    Global rules apply to all devices. A per-device rule for the
                    same condition overrides its global default. Unsupported
                    metrics do not trigger threshold alerts.
                </p>
                {rules.isPending && <p role="status">Loading rules…</p>}
                {rules.isError && (
                    <p role="alert" className="error">
                        {rules.error.message}
                    </p>
                )}
                {rules.data?.length === 0 && <p>No alert rules configured.</p>}
                <div className="table-wrap" tabIndex={0} role="region" aria-label="Alert rules">
                    <table>
                        <thead>
                            <tr>
                                <th>Rule / scope</th>
                                <th>Condition</th>
                                <th>Settings</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rules.data?.map((rule) => (
                                <tr key={rule.id}>
                                    <td>
                                        {rule.name}
                                        <div className="muted">
                                            {rule.device_id
                                                ? (devices.data?.find(
                                                      (item) =>
                                                          item.id ===
                                                          rule.device_id,
                                                  )?.name ?? rule.device_id)
                                                : "Global default"}
                                        </div>
                                    </td>
                                    <td>
                                        {labels[rule.condition]}
                                        <div>
                                            {rule.severity} ·{" "}
                                            {rule.enabled
                                                ? "Enabled"
                                                : "Disabled"}
                                        </div>
                                    </td>
                                    <td>
                                        {rule.threshold} {unit(rule.condition)}
                                        <div className="muted">
                                            Sustain {rule.duration_seconds}s ·
                                            hysteresis {rule.hysteresis}
                                        </div>
                                    </td>
                                    <td>
                                        <button
                                            className="button"
                                            disabled={disabled}
                                            onClick={() => {
                                                setEditing(rule);
                                                const { id: _id, ...value } =
                                                    rule;
                                                void _id;
                                                setDraft(value);
                                            }}
                                            aria-label={`Edit ${rule.name}`}
                                        >
                                            Edit
                                        </button>
                                        <button
                                            className="button"
                                            disabled={disabled}
                                            onClick={() => setRemoving(rule)}
                                            aria-label={`Delete ${rule.name}`}
                                        >
                                            Delete
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <h3>{editing ? `Edit ${editing.name}` : "Add rule"}</h3>
                <form onSubmit={save} className="grid">
                    <label className="field">
                        Rule name
                        <input
                            required
                            maxLength={120}
                            value={draft.name}
                            onChange={(e) =>
                                setDraft({ ...draft, name: e.target.value })
                            }
                        />
                    </label>
                    <label className="field">
                        Condition
                        <select
                            value={draft.condition}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    condition: e.target.value as Condition,
                                    threshold: e.target.value.includes(
                                        "temperature",
                                    )
                                        ? 45
                                        : [
                                                "offline",
                                                "telemetry_stale",
                                            ].includes(e.target.value)
                                          ? 300
                                          : ["cpu_high", "memory_high"].includes(e.target.value)
                                            ? 0.9
                                            : 0.2,
                                    hysteresis: e.target.value.includes(
                                        "temperature",
                                    )
                                        ? 2
                                        : [
                                                "offline",
                                                "telemetry_stale",
                                            ].includes(e.target.value)
                                          ? 0
                                          : 0.05,
                                })
                            }
                        >
                            {Object.entries(labels).map(([value, label]) => (
                                <option key={value} value={value}>
                                    {label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="field">
                        Rule scope
                        <select
                            value={draft.device_id ?? ""}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    device_id: e.target.value || null,
                                })
                            }
                        >
                            <option value="">Global default</option>
                            {devices.data?.map((item) => (
                                <option key={item.id} value={item.id}>
                                    {item.name}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="field">
                        Rule severity
                        <select
                            value={draft.severity}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    severity: e.target.value as Severity,
                                })
                            }
                        >
                            <option>info</option>
                            <option>warning</option>
                            <option>critical</option>
                        </select>
                    </label>
                    <label className="field">
                        Threshold ({unit(draft.condition)})
                        <input
                            required
                            type="number"
                            step="any"
                            min="0"
                            max={
                                unit(draft.condition).startsWith("ratio")
                                    ? 1
                                    : draft.condition.includes("temperature") ? 200 : 86400
                            }
                            value={draft.threshold}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    threshold: Number(e.target.value),
                                })
                            }
                        />
                    </label>
                    <label className="field">
                        Sustained duration (seconds)
                        <input
                            required
                            type="number"
                            min="0"
                            max="86400"
                            step="any"
                            value={draft.duration_seconds}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    duration_seconds: Number(e.target.value),
                                })
                            }
                        />
                    </label>
                    <label className="field">
                        Recovery hysteresis ({unit(draft.condition)})
                        <input
                            required
                            type="number"
                            min="0"
                            step="any"
                            value={draft.hysteresis}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    hysteresis: Number(e.target.value),
                                })
                            }
                        />
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={draft.enabled}
                            onChange={(e) =>
                                setDraft({
                                    ...draft,
                                    enabled: e.target.checked,
                                })
                            }
                        />{" "}
                        Rule enabled
                    </label>
                    <div>
                        <button className="button" disabled={disabled}>
                            {mutation.isPending
                                ? "Saving…"
                                : editing
                                  ? "Save rule"
                                  : "Create rule"}
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
            {removing && (
                <Confirmation
                    title={`Delete ${removing.name}?`}
                    onCancel={() => setRemoving(null)}
                >
                    <p>
                        The rule will no longer evaluate. Existing alert history
                        is retained.
                    </p>
                    <button
                        className="button"
                        disabled={disabled}
                        onClick={() =>
                            mutation.mutate({
                                path: `/api/v1/alerts/rules/${removing.id}`,
                                method: "DELETE",
                            })
                        }
                    >
                        Confirm delete
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
