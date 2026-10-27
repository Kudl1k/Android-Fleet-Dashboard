import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
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
import StatusChip from "../../components/StatusChip";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    ChevronRight,
    Copy,
    Eraser,
    Maximize2,
    RotateCw,
    SquareTerminal,
    X,
} from "lucide-react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import "./terminal.css";
import RunDetail, {
    RunStatus,
    useRunElapsed,
    type RunRecord,
} from "../runs/RunDetail";
import { formatDuration } from "../runs/runOutput";
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
function stateLed(state: string) {
    if (state === "active") return "online";
    if (state === "connecting") return "degraded";
    if (state === "failed" || state === "timed_out") return "critical";
    return "";
}
function terminalTheme() {
    const css = getComputedStyle(document.documentElement);
    const light = document.documentElement.dataset.theme === "light";
    return {
        background:
            css.getPropertyValue("--inset").trim() ||
            (light ? "#e9edf1" : "#0c0f13"),
        foreground:
            css.getPropertyValue("--text").trim() ||
            (light ? "#141920" : "#e8ecf1"),
        cursor: css.getPropertyValue("--accent").trim() || "#72a9ff",
        selectionBackground: light ? "#1d5ccc40" : "#72a9ff55",
    };
}
function TerminalTab({
    target,
    onClose,
    onStateChange,
}: {
    target: Target;
    onClose: () => void;
    onStateChange?: (state: string) => void;
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
            fontSize: 13,
            lineHeight: 1.25,
            fontFamily:
                'ui-monospace, "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace',
            theme: terminalTheme(),
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
            term.options.theme = terminalTheme();
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
    useEffect(() => {
        onStateChange?.(state);
    }, [state, onStateChange]);
    return (
        <div className="terminal-tab">
            <div className="terminal-toolbar">
                <span className="terminal-status" role="status">
                    <span className={`led ${stateLed(state)}`} />
                    {state.replaceAll("_", " ")}
                </span>
                <div
                    className="terminal-tools"
                    role="group"
                    aria-label="Terminal session tools"
                >
                    <Button
                        variant="ghost"
                        onClick={() => {
                            setError("");
                            setState("connecting");
                            setGeneration(generation + 1);
                        }}
                    >
                        <RotateCw aria-hidden="true" />
                        <span className="terminal-tool-label">Reconnect</span>
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() => terminal.current?.clear()}
                    >
                        <Eraser aria-hidden="true" />
                        <span className="terminal-tool-label">Clear</span>
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() => {
                            const value = terminal.current?.getSelection();
                            if (value)
                                void navigator.clipboard?.writeText(value);
                        }}
                    >
                        <Copy aria-hidden="true" />
                        <span className="terminal-tool-label">
                            Copy selection
                        </span>
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() =>
                            void element.current?.parentElement?.requestFullscreen()
                        }
                    >
                        <Maximize2 aria-hidden="true" />
                        <span className="terminal-tool-label">Fullscreen</span>
                    </Button>
                </div>
                <Button
                    variant="destructive"
                    className="terminal-close"
                    onClick={() => {
                        void request(
                            `/api/v1/terminal/sessions/${sessionId.current}`,
                            { method: "DELETE" },
                        )
                            .then(onClose)
                            .catch((err) => setError(err.message));
                    }}
                >
                    <X aria-hidden="true" />
                    <span className="terminal-tool-label">Close session</span>
                </Button>
            </div>
            {error && (
                <p role="alert" className="error terminal-error">
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
    const [openedRun, setOpenedRun] = useState<string | null>(null);
    const selectedProfile =
        profiles.find((p) => p.id === profile) ??
        (initialProfile?.id === profile ? initialProfile : undefined);
    const [history, setHistory] = useState<HistoryItem[]>([]);
    const runActive = history.some(
        (item) => item.command && item.state === "active",
    );
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
        // Poll faster while a program run is in progress.
        const timer = setInterval(load, runActive ? 3000 : 15000);
        return () => {
            disposed = true;
            clearInterval(timer);
        };
    }, [runActive]);
    const [historySearch, setHistorySearch] = useState("");
    const deviceHistory = history.filter(
        (item) => !deviceId || item.device_id === deviceId,
    );
    const openedRunItem = history.find((item) => item.id === openedRun);
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
        setTabs((current) => {
            const same = current.filter(
                (tab) => tab.name.replace(/ \d+$/, "") === name,
            ).length;
            return [
                ...current,
                { key, target, name: same ? `${name} ${same + 1}` : name },
            ];
        });
        setActive(key);
    };
    const [tabStates, setTabStates] = useState<Record<string, string>>({});
    const tabStateHandlers = useRef(new Map<string, (state: string) => void>());
    const tabStateHandler = useCallback((key: string) => {
        let handler = tabStateHandlers.current.get(key);
        if (!handler) {
            handler = (state: string) =>
                setTabStates((current) =>
                    current[key] === state
                        ? current
                        : { ...current, [key]: state },
                );
            tabStateHandlers.current.set(key, handler);
        }
        return handler;
    }, []);
    if (!canView) return null;
    return (
        <section className={`terminal-panel${deviceId ? "" : " panel"}`}>
            {!deviceId && <h2>Terminal</h2>}
            <div className="terminal-launch">
                {deviceId && (
                    <FieldSet className="terminal-launch-group">
                        <FieldLegend>ADB shell</FieldLegend>
                        <div className="terminal-launch-row">
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
                    <FieldSet className="terminal-launch-group terminal-launch-ssh">
                        <FieldLegend>SSH connection</FieldLegend>
                        <div className="terminal-launch-row">
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
                        </div>
                    </FieldSet>
                )}
            </div>
            {error && (
                <p className="error" role="alert">
                    {error}
                </p>
            )}
            <div className="terminal-window">
                {tabs.length > 0 ? (
                    <Tabs
                        className="terminal-tabs"
                        value={active}
                        onValueChange={setActive}
                    >
                        <TabsList aria-label="Terminal sessions">
                            {tabs.map((tab) => (
                                <TabsTrigger value={tab.key} key={tab.key}>
                                    <span
                                        className={`led ${stateLed(tabStates[tab.key] ?? "connecting")}`}
                                    />
                                    {tab.name}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                        {tabs.map((tab) => (
                            <TabsContent
                                value={tab.key}
                                key={tab.key}
                                forceMount
                                hidden={active !== tab.key}
                            >
                                <TerminalTab
                                    target={tab.target}
                                    onStateChange={tabStateHandler(tab.key)}
                                    onClose={() => {
                                        setTabs((current) =>
                                            current.filter(
                                                (t) => t.key !== tab.key,
                                            ),
                                        );
                                        if (active === tab.key)
                                            setActive(
                                                tabs.find(
                                                    (t) => t.key !== tab.key,
                                                )?.key ?? "",
                                            );
                                    }}
                                />
                            </TabsContent>
                        ))}
                    </Tabs>
                ) : (
                    <div className="terminal-empty">
                        <SquareTerminal size={28} aria-hidden="true" />
                        <p>
                            <strong>No open terminal</strong>
                        </p>
                        <p className="muted">
                            {deviceId
                                ? "Open an ADB shell or an SSH connection above. Several sessions can run side by side in tabs."
                                : "Open the SSH connection above to start a session."}
                        </p>
                    </div>
                )}
            </div>
            <p className="terminal-hint muted">
                <kbd>Ctrl+Shift+C</kbd> copies selection ·{" "}
                <kbd>Ctrl+Shift+L</kbd> clears output · Sessions keep running
                after you leave the page (up to the configured lifetime); use
                Close session to end them.
            </p>
            {canSSH && (
                <div className="device-program-run">
                    <h3>Run a program</h3>
                    <p className="muted">
                        {selectedProfile
                            ? `Runs over ${selectedProfile.name} (${selectedProfile.username}@${selectedProfile.host}) and saves the result below.`
                            : "Select an SSH connection above first. The run opens in a terminal tab and its result is saved below."}
                    </p>
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
                    {selectedProfile && !selectedProfile.device_id && (
                        <p className="muted">
                            Link this SSH profile to an Android device to record
                            its statistics.
                        </p>
                    )}
                    <p className="muted terminal-run-note">
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
                    <ul className="session-cards">
                        {filteredHistory.map((item) => (
                            <li key={item.id}>
                                <HistoryCard
                                    item={item}
                                    onOpen={() => setOpenedRun(item.id)}
                                    onResume={() =>
                                        open(
                                            {
                                                connection_type:
                                                    item.connection_type,
                                                profile_id: item.profile_id,
                                                device_id: item.device_id,
                                                session_id: item.id,
                                            },
                                            "Resumed session",
                                        )
                                    }
                                    onClose={() => {
                                        void request(
                                            `/api/v1/terminal/sessions/${item.id}`,
                                            { method: "DELETE" },
                                        )
                                            .then(() =>
                                                setHistory((current) =>
                                                    current.map((session) =>
                                                        session.id === item.id
                                                            ? {
                                                                  ...session,
                                                                  state: "closed",
                                                              }
                                                            : session,
                                                    ),
                                                ),
                                            )
                                            .catch((err) =>
                                                setError(err.message),
                                            );
                                    }}
                                />
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
            {openedRunItem && (
                <RunDetail
                    run={openedRunItem}
                    onClose={() => setOpenedRun(null)}
                />
            )}
        </section>
    );
}
type HistoryItem = RunRecord & {
    connection_type: "adb" | "ssh";
    profile_id?: string;
    device_id?: string;
    command?: string;
};
function HistoryCard({
    item,
    onOpen,
    onResume,
    onClose,
}: {
    item: HistoryItem;
    onOpen: () => void;
    onResume: () => void;
    onClose: () => void;
}) {
    const elapsed = useRunElapsed(item);
    const started = item.created_at
        ? new Date(item.created_at * 1000).toLocaleString()
        : undefined;
    if (item.command) {
        const samples = item.device_recording?.enabled
            ? `${item.device_recording.sample_count} samples`
            : "no device statistics";
        return (
            <button
                type="button"
                className="session-card"
                onClick={onOpen}
                aria-label={`Open run details: ${item.command}`}
            >
                <RunStatus run={item} />
                <span className="session-card-main">
                    <code className="session-card-title">{item.command}</code>
                    <span className="session-card-meta">
                        {[started, formatDuration(elapsed), samples]
                            .filter(Boolean)
                            .join(" · ")}
                    </span>
                </span>
                <span className="session-card-open" aria-hidden="true">
                    <span>Details</span>
                    <ChevronRight size={18} />
                </span>
            </button>
        );
    }
    const active = item.state === "active";
    return (
        <div className="session-card">
            <StatusChip
                value={active ? "running" : item.state}
                label={active ? "active" : item.state.replaceAll("_", " ")}
            />
            <span className="session-card-main">
                <span className="session-card-title">
                    {item.connection_type === "adb"
                        ? "ADB shell"
                        : "SSH session"}
                </span>
                <span className="session-card-meta">
                    {[
                        started,
                        formatDuration(elapsed),
                        item.termination_reason?.replaceAll("_", " "),
                    ]
                        .filter(Boolean)
                        .join(" · ")}
                </span>
            </span>
            {active && (
                <span className="session-card-actions">
                    <Button variant="outline" onClick={onResume}>
                        Resume session
                    </Button>
                    <Button variant="destructive" onClick={onClose}>
                        Close session
                    </Button>
                </span>
            )}
        </div>
    );
}
