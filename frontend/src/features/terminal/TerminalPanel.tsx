import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import Disclosure from "@/components/Disclosure";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    NativeSelect,
    NativeSelectOption,
} from "@/components/ui/native-select";
import {
    Field,
    FieldLabel,
    FieldSet,
    FieldLegend,
    FieldGroup,
} from "@/components/ui/field";
import ListRegion from "../../components/ListRegion";
import StateBadge from "../../components/StateBadge";
import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import "./terminal.css";
import RunTelemetry, { type DeviceRecording } from "./RunTelemetry";
export interface SSHProfile {
    id: string;
    name: string;
    host: string;
    port: number;
    username: string;
    enabled: boolean;
    device_id?: string | null;
    auth_method: string;
    fingerprint?: string | null;
    allowed_identities?: string[];
}
type Target = {
    connection_type: "adb" | "ssh";
    device_id?: string;
    profile_id?: string;
    command?: string;
    record_device?: boolean;
    sample_interval?: number;
    session_id?: string;
};
type Tab = { key: string; name: string; target: Target };
export function chunkTerminalInput(data: string): string[] {
    const encoder = new TextEncoder();
    const overhead = encoder.encode(
        JSON.stringify({ version: 1, type: "input", data: "" }),
    ).byteLength;
    const chunks: string[] = [];
    let chunk = "";
    let bytes = overhead;
    for (const point of data) {
        const size = encoder.encode(
            JSON.stringify(point).slice(1, -1),
        ).byteLength;
        if (bytes + size > 4096) {
            chunks.push(chunk);
            chunk = "";
            bytes = overhead;
        }
        chunk += point;
        bytes += size;
    }
    if (chunk) chunks.push(chunk);
    return chunks;
}
function TerminalTab({
    target,
    onClose,
}: {
    target: Target;
    onClose: () => void;
}) {
    const element = useRef<HTMLDivElement>(null);
    const terminal = useRef<Terminal | null>(null);
    const cleanup = useRef<Promise<void>>(Promise.resolve());
    const [state, setState] = useState("connecting");
    const [error, setError] = useState("");
    const [generation, setGeneration] = useState(0);
    const { token } = useAuth();
    const sessionId = useRef(target.session_id ?? "");
    useEffect(() => {
        const previousCleanup = cleanup.current;
        let localSocket: WebSocket | null = null;
        let disposed = false;
        let heartbeat: ReturnType<typeof setInterval> | undefined;
        const term = new Terminal({
            cursorBlink: true,
            scrollback: 2000,
            fontSize: 14,
            theme:
                document.documentElement.dataset.theme === "light"
                    ? { background: "#ffffff", foreground: "#111827" }
                    : { background: "#111827", foreground: "#e5e7eb" },
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        terminal.current = term;
        term.open(element.current!);
        const send = (message: Record<string, unknown>) => {
            if (!disposed && localSocket?.readyState === WebSocket.OPEN)
                localSocket.send(JSON.stringify({ version: 1, ...message }));
        };
        const resize = () => {
            try {
                fit.fit();
                if (term.cols > 0 && term.rows > 0)
                    send({ type: "resize", cols: term.cols, rows: term.rows });
            } catch {
                /* hidden tab has no dimensions */
            }
        };
        const observer = new ResizeObserver(resize);
        observer.observe(element.current!);
        resize();
        const themeObserver = new MutationObserver(() => {
            term.options.theme =
                document.documentElement.dataset.theme === "light"
                    ? { background: "#ffffff", foreground: "#111827" }
                    : { background: "#111827", foreground: "#e5e7eb" };
        });
        themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["data-theme"],
        });
        const input = term.onData((data) => {
            for (const chunk of chunkTerminalInput(data))
                send({ type: "input", data: chunk });
        });
        term.attachCustomKeyEventHandler((event) => {
            if (
                event.type === "keydown" &&
                event.ctrlKey &&
                event.shiftKey &&
                event.code === "KeyC"
            ) {
                void navigator.clipboard?.writeText(term.getSelection());
                return false;
            }
            if (
                event.type === "keydown" &&
                event.ctrlKey &&
                event.shiftKey &&
                event.code === "KeyL"
            ) {
                term.clear();
                return false;
            }
            return true;
        });
        async function connect() {
            try {
                await previousCleanup;
                if (disposed) return;
                const created = sessionId.current
                    ? { id: sessionId.current }
                    : await request<{ id: string }>(
                          "/api/v1/terminal/sessions",
                          {
                              method: "POST",
                              body: JSON.stringify({
                                  ...target,
                                  cols: term.cols,
                                  rows: term.rows,
                              }),
                          },
                      );
                sessionId.current = created.id;
                if (disposed) return;
                let ticket: { ticket: string; protocol: string };
                try {
                    ticket = await request<{
                        ticket: string;
                        protocol: string;
                    }>(`/api/v1/terminal/sessions/${created.id}/ticket`, {
                        method: "POST",
                    });
                } catch (err) {
                    const result = await request<{
                        state: string;
                        output?: string;
                        termination_reason?: string;
                    }>(`/api/v1/terminal/sessions/${created.id}`);
                    if (disposed) return;
                    if (
                        result.state !== "active" &&
                        result.state !== "connecting"
                    ) {
                        setState(result.state);
                        if (result.output) term.write(result.output);
                        if (result.termination_reason)
                            setError(result.termination_reason);
                        return;
                    }
                    throw err;
                }
                if (disposed) return;
                const url = new URL(
                    `/api/v1/terminal/sessions/${created.id}/stream`,
                    window.location.href,
                );
                url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
                const ws = new WebSocket(url, [
                    ticket.protocol,
                    `ticket.${ticket.ticket}`,
                ]);
                localSocket = ws;
                ws.onopen = () => {
                    if (disposed) {
                        ws.close();
                        return;
                    }
                    setState("active");
                    resize();
                    heartbeat = setInterval(
                        () => send({ type: "heartbeat" }),
                        15000,
                    );
                };
                ws.onmessage = (event) => {
                    if (disposed) return;
                    try {
                        if (
                            typeof event.data !== "string" ||
                            event.data.length > 500000
                        )
                            throw new Error("Invalid terminal message");
                        const message = JSON.parse(event.data);
                        if (message.version !== 1)
                            throw new Error("Unsupported terminal protocol");
                        if (
                            message.type === "output" &&
                            typeof message.data === "string"
                        )
                            term.write(message.data);
                        else if (message.type === "status") {
                            setState(message.state);
                            if (message.reason) setError(message.reason);
                        } else if (message.type === "error")
                            setError(message.detail ?? "Terminal failed");
                    } catch {
                        setError("Invalid terminal response");
                        ws.close();
                    }
                };
                ws.onclose = () => {
                    if (!disposed)
                        setState((previous) =>
                            ["failed", "timed_out"].includes(previous)
                                ? previous
                                : "closed",
                        );
                };
                ws.onerror = () => {
                    if (!disposed)
                        setError(
                            "Terminal connection failed. Check the proxy and permissions.",
                        );
                };
            } catch (err) {
                if (!disposed) {
                    setState("failed");
                    setError(
                        err instanceof Error
                            ? err.message
                            : "Connection failed",
                    );
                }
            }
        }
        const connecting = connect();
        return () => {
            disposed = true;
            if (heartbeat) clearInterval(heartbeat);
            observer.disconnect();
            themeObserver.disconnect();
            input.dispose();
            localSocket?.close();
            cleanup.current = connecting.then(() => {}).catch(() => {});
            term.dispose();
            if (terminal.current === term) terminal.current = null;
        };
    }, [target, generation, token]);
    return (
        <div className="terminal-tab">
            <div className="device-session-toolbar">
                <Badge variant="outline" role="status">
                    {state.replaceAll("_", " ")}
                </Badge>
                <div
                    className="actions device-actions"
                    role="group"
                    aria-label="Terminal session tools"
                >
                    <Button
                        variant="outline"
                        onClick={() => {
                            setError("");
                            setState("connecting");
                            setGeneration(generation + 1);
                        }}
                    >
                        Reconnect
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => terminal.current?.clear()}
                    >
                        Clear
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => {
                            const value = terminal.current?.getSelection();
                            if (value)
                                void navigator.clipboard?.writeText(value);
                        }}
                    >
                        Copy selection
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() =>
                            void element.current?.parentElement?.requestFullscreen()
                        }
                    >
                        Fullscreen
                    </Button>
                </div>
                <Button
                    variant="destructive"
                    onClick={() => {
                        void request(
                            `/api/v1/terminal/sessions/${sessionId.current}`,
                            { method: "DELETE" },
                        )
                            .then(onClose)
                            .catch((err) => setError(err.message));
                    }}
                >
                    Close session
                </Button>
            </div>
            {error && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
            <div
                ref={element}
                className="terminal-viewport"
                aria-label="Interactive terminal"
            />
        </div>
    );
}
export default function TerminalPanel({
    deviceId,
    online = true,
    initialProfile,
    onSessionCountChange,
}: {
    deviceId?: string;
    online?: boolean;
    initialProfile?: SSHProfile;
    onSessionCountChange?: (count: number) => void;
}) {
    const auth = useAuth();
    const canSSH = auth.can("terminal:ssh");
    const canView = auth.can("terminal:view");
    const [tabs, setTabs] = useState<Tab[]>([]);
    const [active, setActive] = useState("");
    const [profiles, setProfiles] = useState<SSHProfile[]>([]);
    const [profile, setProfile] = useState(initialProfile?.id ?? "");
    const [error, setError] = useState("");
    useEffect(() => {
        if (!canSSH) return;
        const controller = new AbortController();
        const load = () => {
            void request<SSHProfile[]>("/api/v1/ssh/profiles", {
                signal: controller.signal,
            })
                .then((profiles) => {
                    if (!controller.signal.aborted) {
                        setProfiles(profiles);
                        setError("");
                    }
                })
                .catch((err) => {
                    if (!controller.signal.aborted) setError(err.message);
                });
        };
        load();
        const timer = setInterval(load, 15000);
        return () => {
            controller.abort();
            clearInterval(timer);
        };
    }, [canSSH]);
    const [command, setCommand] = useState("");
    const [recordDevice, setRecordDevice] = useState(true);
    const [expanded, setExpanded] = useState<string | null>(null);
    const selectedProfile =
        profiles.find((p) => p.id === profile) ??
        (initialProfile?.id === profile ? initialProfile : undefined);
    const [history, setHistory] = useState<
        Array<{
            id: string;
            connection_type: "adb" | "ssh";
            device_id?: string;
            profile_id?: string;
            command?: string;
            output?: string;
            output_truncated?: boolean;
            state: string;
            device_recording?: DeviceRecording;
        }>
    >([]);
    const [historyLoading, setHistoryLoading] = useState(true);
    const [historyError, setHistoryError] = useState("");
    useEffect(() => {
        let disposed = false;
        const load = () => {
            void request<{ items: typeof history }>("/api/v1/terminal/sessions")
                .then((result) => {
                    if (!disposed) {
                        setHistory(result.items ?? []);
                        setHistoryError("");
                    }
                })
                .catch((err) => {
                    if (!disposed)
                        setHistoryError(
                            err instanceof Error
                                ? err.message
                                : "Session history unavailable.",
                        );
                })
                .finally(() => {
                    if (!disposed) setHistoryLoading(false);
                });
        };
        load();
        const timer = setInterval(load, 15000);
        return () => {
            disposed = true;
            clearInterval(timer);
        };
    }, []);
    const [historySearch, setHistorySearch] = useState("");
    const deviceHistory = history.filter(
        (item) => !deviceId || item.device_id === deviceId,
    );
    const filteredHistory = deviceHistory.filter((item) =>
        [item.command, item.id, item.connection_type, item.state]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(historySearch.toLowerCase()),
    );
    useEffect(() => {
        onSessionCountChange?.(canView ? tabs.length : 0);
    }, [tabs.length, canView, onSessionCountChange]);
    const nextTabId = useRef(0);
    const open = (target: Target, name: string) => {
        const key = String(nextTabId.current++);
        setTabs((current) => [...current, { key, target, name }]);
        setActive(key);
    };
    if (!canView) return null;
    return (
        <section className="panel terminal-panel">
            <h2>Terminal</h2>
            <p className="muted">
                Sessions survive browser closure while the backend runs, up to
                the configured lifetime. Use Close session to terminate.
                Interactive access is privileged. Sessions start only when you
                open a tab. Ctrl+Shift+C copies selection; Ctrl+Shift+L clears
                output.
            </p>
            <div className="device-connection-groups">
                {deviceId && (
                    <FieldSet className="device-action-group">
                        <FieldLegend>ADB shell</FieldLegend>
                        <div className="actions device-actions">
                            <Button
                                variant="default"
                                disabled={!auth.can("terminal:adb") || !online}
                                onClick={() =>
                                    open(
                                        {
                                            connection_type: "adb",
                                            device_id: deviceId,
                                        },
                                        "ADB Shell",
                                    )
                                }
                            >
                                Open ADB Shell
                            </Button>
                        </div>
                    </FieldSet>
                )}
                {auth.can("terminal:ssh") && (
                    <FieldSet className="device-action-group">
                        <FieldLegend>SSH connection</FieldLegend>
                        <FieldGroup className="actions device-actions device-form-row">
                            <NativeSelect
                                aria-label="SSH connection"
                                value={profile}
                                onChange={(e) => setProfile(e.target.value)}
                            >
                                <NativeSelectOption value="">
                                    Select SSH connection
                                </NativeSelectOption>
                                {(initialProfile
                                    ? [
                                          initialProfile,
                                          ...profiles.filter(
                                              (p) => p.id !== initialProfile.id,
                                          ),
                                      ]
                                    : profiles
                                )
                                    .filter(
                                        (p) =>
                                            p.enabled &&
                                            (!deviceId ||
                                                !p.device_id ||
                                                p.device_id === deviceId),
                                    )
                                    .map((p) => (
                                        <NativeSelectOption
                                            key={p.id}
                                            value={p.id}
                                        >
                                            {p.name}
                                        </NativeSelectOption>
                                    ))}
                            </NativeSelect>
                            <Button
                                variant="outline"
                                disabled={!profile}
                                onClick={() =>
                                    open(
                                        {
                                            connection_type: "ssh",
                                            profile_id: profile,
                                        },
                                        profiles.find((p) => p.id === profile)
                                            ?.name ??
                                            initialProfile?.name ??
                                            "SSH",
                                    )
                                }
                            >
                                Open SSH
                            </Button>
                        </FieldGroup>
                    </FieldSet>
                )}
            </div>
            {error && (
                <p className="error" role="alert">
                    {error}
                </p>
            )}
            {canSSH && (
                <div className="device-program-run">
                    <h3>Run a program</h3>
                    <FieldGroup className="actions device-actions device-form-row">
                        <Field>
                            <FieldLabel>
                                Program command
                                <Input
                                    value={command}
                                    onChange={(e) => setCommand(e.target.value)}
                                    placeholder="python3 benchmark.py"
                                    maxLength={4096}
                                />
                            </FieldLabel>
                        </Field>
                        <Button
                            variant="default"
                            disabled={!profile || !command.trim()}
                            onClick={() =>
                                open(
                                    {
                                        connection_type: "ssh",
                                        profile_id: profile,
                                        command,
                                        ...(recordDevice &&
                                        selectedProfile?.device_id
                                            ? {
                                                  record_device: true,
                                                  sample_interval: 15,
                                              }
                                            : {}),
                                    },
                                    "Recorded run",
                                )
                            }
                        >
                            Record run
                        </Button>
                    </FieldGroup>
                    <Field>
                        <FieldLabel className="device-record-option">
                            <Checkbox
                                checked={recordDevice}
                                disabled={!selectedProfile?.device_id}
                                onCheckedChange={(value) =>
                                    setRecordDevice(value === true)
                                }
                            />
                            Record device statistics (15 seconds)
                        </FieldLabel>
                    </Field>
                    {!selectedProfile?.device_id && (
                        <span className="muted">
                            Link this SSH profile to an Android device to record
                            its statistics.
                        </span>
                    )}
                    <p className="muted">
                        Requires GNU time (-v) on the SSH host. Saves output,
                        CPU utilization, CPU time, elapsed time and peak RAM for
                        the command and its waited-for children. Output may
                        contain sensitive data.
                    </p>
                </div>
            )}
            <section className="device-session-history">
                <div className="device-list-heading">
                    <h3>Sessions and recorded results</h3>
                    <span className="muted">
                        {filteredHistory.length} of {deviceHistory.length}{" "}
                        loaded
                    </span>
                </div>
                <Field>
                    <FieldLabel className="device-list-filter">
                        Search sessions
                        <Input
                            type="search"
                            value={historySearch}
                            onChange={(event) =>
                                setHistorySearch(event.target.value)
                            }
                        />
                    </FieldLabel>
                </Field>
                {historyError && (
                    <p role="alert" className="error">
                        {historyError}
                    </p>
                )}
                <ListRegion label="Sessions and recorded results">
                    {historyLoading && (
                        <p role="status">Loading session history…</p>
                    )}
                    <ul className="device-session-list">
                        {filteredHistory.map((item) => (
                            <li key={item.id}>
                                <Disclosure
                                    className="device-session-record"
                                    title={
                                        <span className="device-session-title">
                                            {item.command ??
                                                item.connection_type}
                                            <small>{item.id}</small>
                                        </span>
                                    }
                                    description={
                                        <StateBadge state={item.state} />
                                    }
                                    onOpenChange={(open) => {
                                        if (open) setExpanded(item.id);
                                        else
                                            setExpanded((current) =>
                                                current === item.id
                                                    ? null
                                                    : current,
                                            );
                                    }}
                                >
                                    <div className="device-run-content">
                                        <div className="actions device-actions device-session-actions">
                                            {item.state === "active" && (
                                                <Button
                                                    variant="outline"
                                                    onClick={() =>
                                                        open(
                                                            {
                                                                connection_type:
                                                                    item.connection_type,
                                                                profile_id:
                                                                    item.profile_id,
                                                                device_id:
                                                                    item.device_id,
                                                                session_id:
                                                                    item.id,
                                                            },
                                                            "Resumed session",
                                                        )
                                                    }
                                                >
                                                    Resume session
                                                </Button>
                                            )}
                                            {item.state === "active" && (
                                                <Button
                                                    variant="destructive"
                                                    onClick={() => {
                                                        void request(
                                                            `/api/v1/terminal/sessions/${item.id}`,
                                                            {
                                                                method: "DELETE",
                                                            },
                                                        )
                                                            .then(() =>
                                                                setHistory(
                                                                    (current) =>
                                                                        current.map(
                                                                            (
                                                                                session,
                                                                            ) =>
                                                                                session.id ===
                                                                                item.id
                                                                                    ? {
                                                                                          ...session,
                                                                                          state: "closed",
                                                                                      }
                                                                                    : session,
                                                                        ),
                                                                ),
                                                            )
                                                            .catch((err) =>
                                                                setError(
                                                                    err.message,
                                                                ),
                                                            );
                                                    }}
                                                >
                                                    Close session
                                                </Button>
                                            )}
                                        </div>
                                        {item.command && (
                                            <>
                                                <pre>
                                                    {item.output ??
                                                        "Waiting for output…"}
                                                </pre>
                                                {item.output_truncated && (
                                                    <p>
                                                        Only the last 65,536
                                                        characters are retained.
                                                    </p>
                                                )}
                                                <Button
                                                    variant="outline"
                                                    onClick={() => {
                                                        const url =
                                                            URL.createObjectURL(
                                                                new Blob(
                                                                    [
                                                                        item.output ??
                                                                            "",
                                                                    ],
                                                                    {
                                                                        type: "text/plain",
                                                                    },
                                                                ),
                                                            );
                                                        const link =
                                                            document.createElement(
                                                                "a",
                                                            );
                                                        link.href = url;
                                                        link.download = `run-${item.id}.txt`;
                                                        link.click();
                                                        URL.revokeObjectURL(
                                                            url,
                                                        );
                                                    }}
                                                >
                                                    Download results
                                                </Button>
                                            </>
                                        )}
                                        {expanded === item.id &&
                                            item.device_recording?.enabled && (
                                                <RunTelemetry
                                                    sessionId={item.id}
                                                    deviceId={item.device_id}
                                                    active={
                                                        item.state === "active"
                                                    }
                                                    recording={
                                                        item.device_recording
                                                    }
                                                />
                                            )}
                                    </div>
                                </Disclosure>
                            </li>
                        ))}
                    </ul>
                    {!historyLoading &&
                        !historyError &&
                        !filteredHistory.length && (
                            <p className="muted list-empty">
                                {deviceHistory.length
                                    ? "No sessions match this search."
                                    : "No sessions or recorded results for this device."}
                            </p>
                        )}
                </ListRegion>
            </section>
            <Tabs value={active} onValueChange={setActive}>
                {tabs.length > 0 && (
                    <TabsList aria-label="Terminal sessions">
                        {tabs.map((tab) => (
                            <TabsTrigger value={tab.key} key={tab.key}>
                                {tab.name}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                )}
                {tabs.map((tab) => (
                    <TabsContent
                        value={tab.key}
                        key={tab.key}
                        forceMount
                        hidden={active !== tab.key}
                    >
                        <TerminalTab
                            target={tab.target}
                            onClose={() => {
                                setTabs((current) =>
                                    current.filter((t) => t.key !== tab.key),
                                );
                                if (active === tab.key)
                                    setActive(
                                        tabs.find((t) => t.key !== tab.key)
                                            ?.key ?? "",
                                    );
                            }}
                        />
                    </TabsContent>
                ))}
            </Tabs>
            {!tabs.length && (
                <p className="muted">
                    No terminal sessions. ADB Shell must first be enabled by an
                    administrator.
                </p>
            )}
        </section>
    );
}
