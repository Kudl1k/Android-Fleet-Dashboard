import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    NativeSelect,
    NativeSelectOption,
} from "@/components/ui/native-select";
import { Field, FieldLabel } from "@/components/ui/field";
import { useEffect, useRef, useState } from "react";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { mapPoint, ScreenDecoder } from "./player";
import "./screen.css";
interface Session {
    id: string;
    state: string;
    control?: boolean;
}
const presets = [
    {
        label: "Low · 480 max edge / 15 FPS",
        max_size: 480,
        max_fps: 15,
        bitrate: 1000000,
    },
    {
        label: "Medium · 720 max edge / 30 FPS",
        max_size: 720,
        max_fps: 30,
        bitrate: 2000000,
    },
    {
        label: "High · 1080 max edge / 30 FPS",
        max_size: 1080,
        max_fps: 30,
        bitrate: 4000000,
    },
];
const keycodes: Record<string, number> = {
    Backspace: 67,
    Enter: 66,
    Escape: 4,
    ArrowUp: 19,
    ArrowDown: 20,
    ArrowLeft: 21,
    ArrowRight: 22,
    Tab: 61,
    Shift: 59,
    Control: 113,
    Alt: 57,
    Delete: 112,
};
export default function LiveScreen({
    id,
    online,
    onStateChange,
}: {
    id: string;
    online: boolean;
    onStateChange?: (state: string) => void;
}) {
    const auth = useAuth(),
        canvas = useRef<HTMLCanvasElement>(null),
        surface = useRef<HTMLDivElement>(null);
    const active = useRef<{
        session: Session;
        socket?: WebSocket;
        decoder?: ScreenDecoder;
        heartbeat?: ReturnType<typeof setInterval>;
        sampling?: ReturnType<typeof setInterval>;
    }>(null);
    const controlEpoch = useRef(0),
        controlPending = useRef(false);
    const heldPointer = useRef<number | null>(null);
    const heldKeys = useRef(new Set<number>());
    const cleanup = useRef<Promise<void>>(Promise.resolve());
    const generation = useRef(0),
        control = useRef(false),
        pending = useRef(false),
        mounted = useRef(true);
    const [state, setState] = useState("stopped"),
        [error, setError] = useState(""),
        [quality, setQuality] = useState(1),
        [owns, setOwns] = useState(false),
        [focused, setFocused] = useState(false),
        [stats, setStats] = useState({
            fps: 0,
            firstFrame: 0,
            dropped: 0,
            received: 0,
            bitrate: 0,
        });
    useEffect(() => {
        onStateChange?.(state);
    }, [state, onStateChange]);
    const send = (message: object) => {
        const ws = active.current?.socket;
        if (ws?.readyState === WebSocket.OPEN && ws.bufferedAmount < 65536)
            ws.send(JSON.stringify(message));
    };
    const dispose = () => {
        const old = active.current;
        active.current = null;
        control.current = false;
        controlEpoch.current++;
        heldKeys.current.clear();
        if (
            heldPointer.current !== null &&
            canvas.current?.hasPointerCapture(heldPointer.current)
        )
            canvas.current.releasePointerCapture(heldPointer.current);
        heldPointer.current = null;
        const c = canvas.current;
        if (c) c.getContext("2d")?.clearRect(0, 0, c.width, c.height);
        if (old) {
            clearInterval(old.heartbeat);
            clearInterval(old.sampling);
            old.socket?.close();
            old.decoder?.close();
            cleanup.current = Promise.all([
                cleanup.current,
                request(`/api/v1/screen/sessions/${old.session.id}`, {
                    method: "DELETE",
                }).catch(() => {}),
            ]).then(() => {});
        }
    };
    const stop = () => {
        generation.current++;
        pending.current = false;
        dispose();
        setOwns(false);
        setState("stopped");
    };
    useEffect(() => {
        mounted.current = true;
        setState("stopped");
        setOwns(false);
        setFocused(false);
        const lifecycle = generation;
        const suspended = () => {
            if (document.hidden && active.current) {
                lifecycle.current++;
                pending.current = false;
                dispose();
                setOwns(false);
                setState("stopped");
                setError(
                    "Playback stopped while the tab was hidden. Restart in view-only mode.",
                );
            }
        };
        document.addEventListener("visibilitychange", suspended);
        return () => {
            document.removeEventListener("visibilitychange", suspended);
            {
                mounted.current = false;
                lifecycle.current++;
                pending.current = false;
                dispose();
            }
        };
    }, [id, auth.token]);
    const start = async () => {
        if (pending.current || active.current) return;
        if (typeof VideoDecoder === "undefined" || !window.isSecureContext) {
            setError(
                "Live playback requires WebCodecs in a secure context. Use current Chromium on localhost or HTTPS.",
            );
            return;
        }
        pending.current = true;
        const run = ++generation.current;
        setStats({
            fps: 0,
            firstFrame: 0,
            dropped: 0,
            received: 0,
            bitrate: 0,
        });
        const started = performance.now();
        setError("");
        setState("starting");
        setOwns(false);
        control.current = false;
        try {
            await cleanup.current;
            if (run !== generation.current || !mounted.current) return;
            const session = await request<Session>(
                `/api/v1/devices/${encodeURIComponent(id)}/screen/sessions`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        ...presets[quality],
                        label: undefined,
                        codec: "h264",
                    }),
                },
            );
            if (run !== generation.current || !mounted.current) {
                await request(`/api/v1/screen/sessions/${session.id}`, {
                    method: "DELETE",
                });
                return;
            }
            active.current = { session };
            const { ticket } = await request<{ ticket: string }>(
                `/api/v1/screen/sessions/${session.id}/ticket`,
                { method: "POST" },
            );
            if (run !== generation.current || !mounted.current) return;
            const url = new URL(
                `/api/v1/screen/sessions/${session.id}/stream`,
                location.href,
            );
            url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
            const socket = new WebSocket(url);
            socket.binaryType = "arraybuffer";
            active.current.socket = socket;
            let frames = 0,
                since = performance.now(),
                previousBytes = 0,
                firstFrame = 0;
            const failed = (message: string) => {
                if (run !== generation.current || !mounted.current) return;
                generation.current++;
                pending.current = false;
                dispose();
                setOwns(false);
                setState("failed");
                setError(message);
            };
            const decoder = new ScreenDecoder(
                (frame) => {
                    if (run !== generation.current || !canvas.current) return;
                    const c = canvas.current;
                    if (
                        c.width !== frame.displayWidth ||
                        c.height !== frame.displayHeight
                    ) {
                        if (control.current)
                            send({
                                type: "pointer",
                                action: "cancel",
                                x: 0,
                                y: 0,
                                width: frame.displayWidth,
                                height: frame.displayHeight,
                                pressure: 0,
                                buttons: 0,
                            });
                        if (
                            heldPointer.current !== null &&
                            c.hasPointerCapture(heldPointer.current)
                        )
                            c.releasePointerCapture(heldPointer.current);
                        heldPointer.current = null;
                    }
                    if (c.width !== frame.displayWidth)
                        c.width = frame.displayWidth;
                    if (c.height !== frame.displayHeight)
                        c.height = frame.displayHeight;
                    c.getContext("2d")?.drawImage(frame, 0, 0);
                    frames++;
                    const now = performance.now();
                    if (!firstFrame) {
                        firstFrame = now - started;
                        setStats((previous) => ({ ...previous, firstFrame }));
                    }
                    setState("streaming");
                },
                (e) => failed(e.message),
            );
            const sampling = setInterval(() => {
                if (run !== generation.current) return;
                const now = performance.now();
                setStats({
                    fps: (frames * 1000) / (now - since),
                    firstFrame,
                    dropped: decoder.dropped,
                    received: decoder.received,
                    bitrate:
                        ((decoder.bytes - previousBytes) * 8) / (now - since),
                });
                previousBytes = decoder.bytes;
                frames = 0;
                since = now;
            }, 1000);
            Object.assign(active.current, { socket, decoder, sampling });
            socket.onopen = () => {
                if (
                    run !== generation.current ||
                    active.current?.socket !== socket
                ) {
                    socket.close();
                    return;
                }
                socket.send(JSON.stringify({ ticket }));
                if (active.current)
                    active.current.heartbeat = setInterval(
                        () => send({ type: "ping" }),
                        10000,
                    );
            };
            let processing = Promise.resolve(),
                queued = 0;
            socket.onmessage = (event) => {
                if (run !== generation.current) return;
                if (typeof event.data === "string") {
                    try {
                        const message = JSON.parse(event.data);
                        if (message.type === "error")
                            failed(
                                message.detail ??
                                    message.message ??
                                    "Streaming failed.",
                            );
                        if (message.type === "status" && message.state) {
                            if (
                                message.control === false ||
                                message.state === "reconnecting"
                            ) {
                                control.current = false;
                                controlEpoch.current++;
                                setOwns(false);
                                heldKeys.current.clear();
                            }
                            setState(message.state);
                            if (
                                ["failed", "stopped", "timed_out"].includes(
                                    message.state,
                                )
                            )
                                failed(
                                    message.reason ??
                                        "Stream ended. Start a new view-only session to reconnect.",
                                );
                        }
                    } catch {
                        failed("Invalid stream message.");
                    }
                } else {
                    if (queued >= 5) {
                        failed(
                            "Browser decoding is too slow. Restart at lower quality.",
                        );
                        return;
                    }
                    queued++;
                    processing = processing
                        .then(() => decoder.packet(event.data as ArrayBuffer))
                        .catch((e) => failed(String(e)))
                        .finally(() => {
                            queued--;
                        });
                }
            };
            socket.onerror = () =>
                failed(
                    "Streaming connection failed. Restart to reconnect in view-only mode.",
                );
            socket.onclose = () =>
                failed(
                    "Streaming disconnected. Control was released. Restart to reconnect in view-only mode.",
                );
        } catch (e) {
            if (run === generation.current && mounted.current) {
                dispose();
                setError(e instanceof Error ? e.message : String(e));
                setState("failed");
            }
        } finally {
            if (run === generation.current) pending.current = false;
        }
    };
    const changeControl = async () => {
        const session = active.current?.session;
        if (!session || controlPending.current) return;
        const epoch = controlEpoch.current;
        controlPending.current = true;
        try {
            if (owns) {
                for (const keycode of heldKeys.current)
                    send({
                        type: "key",
                        action: "up",
                        keycode,
                        repeat: 0,
                        meta: 0,
                    });
                heldKeys.current.clear();
                send({
                    type: "pointer",
                    action: "cancel",
                    x: 0,
                    y: 0,
                    width: canvas.current?.width ?? 1,
                    height: canvas.current?.height ?? 1,
                    pressure: 0,
                    buttons: 0,
                });
            }
            await request(`/api/v1/screen/sessions/${session.id}/control`, {
                method: owns ? "DELETE" : "POST",
            });
            if (
                active.current?.session.id !== session.id ||
                epoch !== controlEpoch.current
            )
                return;
            control.current = !owns;
            setOwns(!owns);
        } catch (e) {
            if (mounted.current)
                setError(e instanceof Error ? e.message : String(e));
        } finally {
            controlPending.current = false;
        }
    };
    const pointer = (
        event: React.PointerEvent<HTMLCanvasElement>,
        action: string,
    ) => {
        if (
            !event.isPrimary ||
            !control.current ||
            !canvas.current ||
            (action === "move" &&
                !canvas.current.hasPointerCapture(event.pointerId))
        )
            return;
        event.preventDefault();
        if (action === "down") {
            canvas.current.focus();
            canvas.current.setPointerCapture(event.pointerId);
            heldPointer.current = event.pointerId;
        }
        send({
            type: "pointer",
            action,
            ...mapPoint(
                event.clientX,
                event.clientY,
                canvas.current.getBoundingClientRect(),
                canvas.current.width,
                canvas.current.height,
            ),
            pressure:
                action === "up" || action === "cancel"
                    ? 0
                    : event.pressure || 0.5,
            buttons: event.buttons & 7,
        });
        if (
            (action === "up" || action === "cancel") &&
            canvas.current.hasPointerCapture(event.pointerId)
        )
            canvas.current.releasePointerCapture(event.pointerId);
        if (action === "up" || action === "cancel") heldPointer.current = null;
    };
    const keyboard = (event: React.KeyboardEvent, action: "down" | "up") => {
        if (!control.current) return;
        const keycode = keycodes[event.key];
        if (keycode) {
            event.preventDefault();
            if (action === "down") heldKeys.current.add(keycode);
            else heldKeys.current.delete(keycode);
            send({
                type: "key",
                action,
                keycode,
                repeat: event.repeat ? 1 : 0,
                meta:
                    (event.shiftKey ? 1 : 0) |
                    (event.altKey ? 2 : 0) |
                    (event.ctrlKey ? 4096 : 0),
            });
        } else if (
            action === "down" &&
            event.key.length === 1 &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
        ) {
            event.preventDefault();
            send({ type: "text", text: event.key });
        }
    };
    const live = ["starting", "streaming", "reconnecting"].includes(state);
    return (
        <section
            className="panel live-screen"
            aria-labelledby="live-screen-title"
        >
            <div className="screen-heading">
                <div>
                    <h2 id="live-screen-title">Live screen</h2>
                    <p className="muted">
                        Authorized ADB video ·{" "}
                        {owns ? "You are controlling this device" : "View-only"}
                    </p>
                </div>
                <Badge variant="outline" role="status">
                    {state}
                </Badge>
            </div>
            {!auth.can("screen:view") ? (
                <p>Screen viewing permission is required.</p>
            ) : (
                <>
                    <div className="screen-toolbar device-screen-toolbar">
                        <Field>
                            <FieldLabel>
                                Stream quality
                                <NativeSelect
                                    value={quality}
                                    disabled={live}
                                    onChange={(e) =>
                                        setQuality(Number(e.target.value))
                                    }
                                >
                                    {presets.map((p, i) => (
                                        <NativeSelectOption key={i} value={i}>
                                            {p.label}
                                        </NativeSelectOption>
                                    ))}
                                </NativeSelect>
                            </FieldLabel>
                        </Field>
                        <div
                            className="actions device-actions"
                            role="group"
                            aria-label="Stream playback"
                        >
                            <Button
                                variant="default"
                                className="device-pending-action"
                                aria-busy={state === "starting"}
                                disabled={live || !online}
                                onClick={() => void start()}
                            >
                                Start view-only
                            </Button>
                            <Button
                                variant="outline"
                                disabled={!live}
                                onClick={stop}
                            >
                                Stop stream
                            </Button>
                        </div>
                        <div
                            className="actions device-actions"
                            role="group"
                            aria-label="Screen interaction"
                        >
                            <Button
                                variant="outline"
                                className="device-control-action"
                                disabled={
                                    state !== "streaming" ||
                                    !auth.can("screen:control")
                                }
                                onClick={() => void changeControl()}
                            >
                                {owns ? "Release control" : "Request control"}
                            </Button>
                            <Button
                                variant="outline"
                                disabled={state !== "streaming"}
                                onClick={() => {
                                    if (!surface.current?.requestFullscreen)
                                        setError("Fullscreen is unavailable.");
                                    else
                                        void surface.current
                                            .requestFullscreen()
                                            .catch(() =>
                                                setError(
                                                    "Fullscreen is unavailable.",
                                                ),
                                            );
                                }}
                            >
                                Fullscreen
                            </Button>
                        </div>
                    </div>
                    {!online && (
                        <p className="muted">
                            Device must be online to start streaming.
                        </p>
                    )}
                    {error && (
                        <p className="error" role="alert">
                            {error}
                        </p>
                    )}
                    <div
                        className={`screen-surface ${owns ? "controlling" : ""}`}
                        ref={surface}
                    >
                        <canvas
                            ref={canvas}
                            width={720}
                            height={1280}
                            tabIndex={owns ? 0 : -1}
                            aria-label={
                                owns
                                    ? "Android screen control surface. Focus to send keys."
                                    : "Live Android screen, view-only"
                            }
                            onFocus={() => setFocused(true)}
                            onBlur={() => {
                                setFocused(false);
                                for (const keycode of heldKeys.current)
                                    send({
                                        type: "key",
                                        action: "up",
                                        keycode,
                                        repeat: 0,
                                        meta: 0,
                                    });
                                heldKeys.current.clear();
                                if (control.current)
                                    send({
                                        type: "pointer",
                                        action: "cancel",
                                        x: 0,
                                        y: 0,
                                        width: canvas.current?.width ?? 1,
                                        height: canvas.current?.height ?? 1,
                                        pressure: 0,
                                        buttons: 0,
                                    });
                            }}
                            onContextMenu={(e) => {
                                if (owns) e.preventDefault();
                            }}
                            onPointerDown={(e) => pointer(e, "down")}
                            onPointerMove={(e) => pointer(e, "move")}
                            onPointerUp={(e) => pointer(e, "up")}
                            onPointerCancel={(e) => pointer(e, "cancel")}
                            onKeyDown={(e) => keyboard(e, "down")}
                            onKeyUp={(e) => keyboard(e, "up")}
                            style={{ touchAction: owns ? "none" : "auto" }}
                        />
                        {state !== "streaming" && (
                            <div className="screen-overlay">
                                {state === "starting"
                                    ? "Connecting to Android video…"
                                    : state === "reconnecting"
                                      ? "Reconnecting…"
                                      : "Start a session to view the live display"}
                            </div>
                        )}
                    </div>
                    <p className="muted">
                        {stats.fps.toFixed(1)} decoded/rendered FPS · First
                        frame {stats.firstFrame.toFixed(0)} ms ·{" "}
                        {stats.bitrate.toFixed(0)} kbit/s received ·{" "}
                        {stats.received} received frames · {stats.dropped}{" "}
                        dropped frames ·{" "}
                        {owns
                            ? focused
                                ? "Keyboard focused"
                                : "Click or focus the screen to type"
                            : "Input disabled"}
                    </p>
                    <div
                        className="screen-toolbar actions device-actions"
                        role="group"
                        aria-label="Android navigation"
                    >
                        {[
                            ["back", "Back"],
                            ["home", "Home"],
                            ["recent", "Recent apps"],
                            ["wake", "Wake screen"],
                            ["volume_down", "Volume −"],
                            ["volume_up", "Volume +"],
                        ].map(([key, label]) => (
                            <Button
                                variant="outline"
                                key={key}
                                disabled={!owns || state !== "streaming"}
                                onClick={() => send({ type: "nav", key })}
                            >
                                {label}
                            </Button>
                        ))}
                    </div>
                    <p className="muted">
                        Quality changes require stopping and restarting.
                        Reconnection always starts view-only. No audio or
                        clipboard synchronization.
                    </p>
                </>
            )}
        </section>
    );
}
