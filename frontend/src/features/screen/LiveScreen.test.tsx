import Disclosure from "@/components/Disclosure";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useState, type ReactNode } from "react";
import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LiveScreen from "./LiveScreen";
import { request } from "../../lib/api";
const auth = {
    token: "test",
    can: (permission: string) => permissions.includes(permission),
};
let permissions: string[] = [];
vi.mock("../../lib/auth", () => ({ useAuth: () => auth }));
vi.mock("../../lib/api", () => ({ request: vi.fn() }));
beforeEach(() => {
    permissions = ["screen:view"];
    vi.clearAllMocks();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
});
describe("live screen permission and lifecycle", () => {
    it("groups playback separately from screen interaction and Android navigation", () => {
        render(<LiveScreen id="d" online />);
        expect(
            within(
                screen.getByRole("group", { name: "Stream playback" }),
            ).getByRole("button", { name: "Start view-only" }),
        ).toBeEnabled();
        expect(
            within(
                screen.getByRole("group", { name: "Screen interaction" }),
            ).getByRole("button", { name: "Request control" }),
        ).toBeDisabled();
        expect(
            within(
                screen.getByRole("group", { name: "Android navigation" }),
            ).getByRole("button", { name: "Home" }),
        ).toBeDisabled();
        expect(request).not.toHaveBeenCalled();
    });
    it("withholds the stream UI without viewing permission", () => {
        permissions = [];
        render(<LiveScreen id="d" online />);
        expect(
            screen.getByText("Screen viewing permission is required."),
        ).toBeInTheDocument();
        expect(request).not.toHaveBeenCalled();
    });
    it("keeps view-only canvas unfocusable and input/navigation disabled", () => {
        render(<LiveScreen id="d" online />);
        expect(
            screen.getByLabelText("Live Android screen, view-only"),
        ).toHaveAttribute("tabindex", "-1");
        expect(
            screen.getByRole("button", { name: "Request control" }),
        ).toBeDisabled();
        expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
    });
    it("does not start offline devices", () => {
        render(<LiveScreen id="d" online={false} />);
        expect(
            screen.getByRole("button", { name: "Start view-only" }),
        ).toBeDisabled();
    });
    it("reports unsupported decoding explicitly", () => {
        vi.stubGlobal("VideoDecoder", undefined);
        render(<LiveScreen id="d" online />);
        fireEvent.click(
            screen.getByRole("button", { name: "Start view-only" }),
        );
        expect(screen.getByRole("alert")).toHaveTextContent("WebCodecs");
        expect(request).not.toHaveBeenCalled();
        vi.unstubAllGlobals();
    });
    it("terminates a session whose creation completes after unmount", async () => {
        vi.stubGlobal("VideoDecoder", class {});
        vi.stubGlobal("isSecureContext", true);
        let complete!: (s: { id: string; state: string }) => void;
        vi.mocked(request)
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        complete = resolve;
                    }),
            )
            .mockResolvedValue(undefined);
        const view = render(<LiveScreen id="d" online />);
        fireEvent.click(
            screen.getByRole("button", { name: "Start view-only" }),
        );
        await waitFor(() => expect(request).toHaveBeenCalled());
        view.unmount();
        complete({ id: "late", state: "starting" });
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "/api/v1/screen/sessions/late",
                { method: "DELETE" },
            ),
        );
        vi.unstubAllGlobals();
    });
});
class FakeSocket {
    static OPEN = 1;
    static current: FakeSocket;
    readyState = 1;
    bufferedAmount = 0;
    binaryType = "";
    onopen?: () => void;
    onclose?: () => void;
    onerror?: () => void;
    onmessage?: (event: { data: string | ArrayBuffer }) => void;
    send = vi.fn();
    close = vi.fn();
    constructor() {
        FakeSocket.current = this;
    }
}
class FakeDecoder {
    static current: FakeDecoder;
    state = "configured";
    decodeQueueSize = 0;
    reset = vi.fn();
    close = vi.fn();
    configure = vi.fn();
    decode = vi.fn();
    static isConfigSupported = vi.fn(async () => ({ supported: true }));
    constructor(
        public callbacks: {
            output: (frame: VideoFrame) => void;
            error: (error: Error) => void;
        },
    ) {
        FakeDecoder.current = this;
    }
}
function ScreenWorkspace({ children }: { children: ReactNode }) {
    const [tab, setTab] = useState("tools");
    return (
        <Tabs value={tab} onValueChange={setTab}>
            <TabsList aria-label="Workspace">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="tools">Tools</TabsTrigger>
            </TabsList>
            <TabsContent
                value="overview"
                forceMount
                hidden={tab !== "overview"}
            >
                Monitoring
            </TabsContent>
            <TabsContent value="tools" forceMount hidden={tab !== "tools"}>
                <Disclosure title="Screen tool">{children}</Disclosure>
            </TabsContent>
        </Tabs>
    );
}
async function connected(onStateChange?: (state: string) => void) {
    permissions.push("screen:control");
    vi.stubGlobal("VideoDecoder", FakeDecoder);
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("isSecureContext", true);
    vi.mocked(request).mockImplementation(async (path) =>
        path.endsWith("/ticket")
            ? { ticket: "private" }
            : { id: "session", state: "starting" },
    );
    const view = render(
        <ScreenWorkspace>
            <LiveScreen id="d" online onStateChange={onStateChange} />
        </ScreenWorkspace>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Screen tool" }));
    fireEvent.click(screen.getByRole("button", { name: "Start view-only" }));
    await waitFor(() => expect(FakeSocket.current).toBeDefined());
    const { act } = await import("@testing-library/react");
    act(() => {
        FakeSocket.current.onopen?.();
        FakeDecoder.current.callbacks.output({
            displayWidth: 1080,
            displayHeight: 2340,
            close: vi.fn(),
        } as unknown as VideoFrame);
    });
    await screen.findByText("streaming");
    return { view, act };
}
describe("connected player interaction", () => {
    beforeEach(() => {
        FakeSocket.current = undefined as unknown as FakeSocket;
    });
    it("reports stream status while a disclosure preserves the session until route cleanup", async () => {
        const status = vi.fn();
        const { view } = await connected(status);
        expect(status).toHaveBeenLastCalledWith("streaming");
        const socket = FakeSocket.current;
        const canvas = screen.getByLabelText("Live Android screen, view-only");
        fireEvent.click(screen.getByText("Screen tool"));
        expect(socket.close).not.toHaveBeenCalled();
        expect(
            vi
                .mocked(request)
                .mock.calls.some(([, options]) => options?.method === "DELETE"),
        ).toBe(false);
        fireEvent.click(screen.getByText("Screen tool"));
        expect(screen.getByLabelText("Live Android screen, view-only")).toBe(
            canvas,
        );
        expect(FakeSocket.current).toBe(socket);
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Overview" }), {
            button: 0,
            ctrlKey: false,
        });
        expect(canvas).not.toBeVisible();
        expect(socket.close).not.toHaveBeenCalled();
        fireEvent.mouseDown(screen.getByRole("tab", { name: "Tools" }), {
            button: 0,
            ctrlKey: false,
        });
        expect(canvas).toBeVisible();
        expect(FakeSocket.current).toBe(socket);
        view.unmount();
        expect(socket.close).toHaveBeenCalled();
        expect(request).toHaveBeenCalledWith(
            "/api/v1/screen/sessions/session",
            { method: "DELETE" },
        );
        vi.unstubAllGlobals();
    });
    it("waits for the previous DELETE before starting a replacement session", async () => {
        const { view, act } = await connected();
        let finish!: (value: unknown) => void;
        vi.mocked(request).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finish = resolve;
                }),
        );
        fireEvent.click(screen.getByRole("button", { name: "Stop stream" }));
        fireEvent.click(
            screen.getByRole("button", { name: "Start view-only" }),
        );
        await act(async () => {});
        expect(
            vi
                .mocked(request)
                .mock.calls.filter(([path]) =>
                    path.endsWith("/screen/sessions"),
                ),
        ).toHaveLength(1);
        await act(async () => {
            finish({});
        });
        await waitFor(() =>
            expect(
                vi
                    .mocked(request)
                    .mock.calls.filter(([path]) =>
                        path.endsWith("/screen/sessions"),
                    ),
            ).toHaveLength(2),
        );
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("uses the requested medium capture ceiling and labels maximum edge accurately", async () => {
        const { view } = await connected();
        const body = vi
            .mocked(request)
            .mock.calls.find(([path]) =>
                path.endsWith("/screen/sessions"),
            )?.[1]?.body;
        expect(JSON.parse(body as string)).toEqual({
            max_size: 720,
            max_fps: 30,
            bitrate: 2000000,
            codec: "h264",
        });
        expect(
            screen.getByRole("option", { name: "Low · 480 max edge / 15 FPS" }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("option", {
                name: "High · 1080 max edge / 30 FPS",
            }),
        ).toBeInTheDocument();
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("authenticates over the first message and never automatically acquires control", async () => {
        const { view } = await connected();
        expect(FakeSocket.current.send).toHaveBeenCalledWith(
            JSON.stringify({ ticket: "private" }),
        );
        expect(
            vi
                .mocked(request)
                .mock.calls.some(([path]) => path.endsWith("/control")),
        ).toBe(false);
        expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("acquires control explicitly and sends keyboard only from the focused surface", async () => {
        const { view } = await connected();
        fireEvent.click(
            screen.getByRole("button", { name: "Request control" }),
        );
        await screen.findByRole("button", { name: "Release control" });
        const canvas = screen.getByLabelText(/Android screen control surface/);
        fireEvent.keyDown(document.body, { key: "a" });
        expect(FakeSocket.current.send).toHaveBeenCalledTimes(1);
        fireEvent.focus(canvas);
        fireEvent.keyDown(canvas, { key: "a" });
        expect(FakeSocket.current.send).toHaveBeenLastCalledWith(
            JSON.stringify({ type: "text", text: "a" }),
        );
        fireEvent.keyDown(canvas, { key: "Shift", shiftKey: true });
        fireEvent.blur(canvas);
        expect(
            FakeSocket.current.send.mock.calls.some(
                ([message]) =>
                    JSON.parse(message).type === "key" &&
                    JSON.parse(message).action === "up",
            ),
        ).toBe(true);
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("revokes control while reconnecting and closes resources on route cleanup", async () => {
        const { view, act } = await connected();
        fireEvent.click(
            screen.getByRole("button", { name: "Request control" }),
        );
        await screen.findByRole("button", { name: "Release control" });
        act(() =>
            FakeSocket.current.onmessage?.({
                data: JSON.stringify({
                    type: "status",
                    state: "reconnecting",
                    control: false,
                }),
            }),
        );
        expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
        view.unmount();
        expect(FakeSocket.current.close).toHaveBeenCalled();
        expect(FakeDecoder.current.close).toHaveBeenCalled();
        expect(request).toHaveBeenCalledWith(
            "/api/v1/screen/sessions/session",
            { method: "DELETE" },
        );
        vi.unstubAllGlobals();
    });
    it("does not restore control when an acquisition finishes after reconnect", async () => {
        const { view, act } = await connected();
        let finish!: (value: unknown) => void;
        vi.mocked(request).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finish = resolve;
                }),
        );
        fireEvent.click(
            screen.getByRole("button", { name: "Request control" }),
        );
        act(() =>
            FakeSocket.current.onmessage?.({
                data: JSON.stringify({
                    type: "status",
                    state: "reconnecting",
                    control: false,
                }),
            }),
        );
        await act(async () => {
            finish({});
        });
        expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
        expect(
            screen.queryByRole("button", { name: "Release control" }),
        ).not.toBeInTheDocument();
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("updates geometry and cancels old gestures on portrait/landscape changes", async () => {
        const { view, act } = await connected();
        fireEvent.click(
            screen.getByRole("button", { name: "Request control" }),
        );
        await screen.findByRole("button", { name: "Release control" });
        const captured = new Set<number>();
        const currentCanvas = screen.getByLabelText(
            /Android screen control surface/,
        ) as HTMLCanvasElement;
        currentCanvas.getBoundingClientRect = vi.fn(
            () => ({ left: 0, top: 0, width: 390, height: 844 }) as DOMRect,
        );
        currentCanvas.setPointerCapture = vi.fn((id: number) => {
            captured.add(id);
        });
        currentCanvas.hasPointerCapture = vi.fn((id: number) =>
            captured.has(id),
        );
        currentCanvas.releasePointerCapture = vi.fn((id: number) => {
            captured.delete(id);
        });
        vi.stubGlobal(
            "PointerEvent",
            class extends MouseEvent {
                pointerId = 7;
                isPrimary = true;
                pressure = 0.5;
            },
        );
        fireEvent.pointerDown(currentCanvas, {
            clientX: 10,
            clientY: 10,
            buttons: 1,
        });
        expect(currentCanvas.setPointerCapture).toHaveBeenCalledWith(7);
        const frame = {
            displayWidth: 2340,
            displayHeight: 1080,
            close: vi.fn(),
        } as unknown as VideoFrame;
        act(() => FakeDecoder.current.callbacks.output(frame));
        const canvas = screen.getByLabelText(/Android screen control surface/);
        expect(currentCanvas.releasePointerCapture).toHaveBeenCalledWith(7);
        const beforeMove = FakeSocket.current.send.mock.calls.length;
        fireEvent.pointerMove(currentCanvas, {
            clientX: 20,
            clientY: 20,
            buttons: 1,
        });
        expect(FakeSocket.current.send).toHaveBeenCalledTimes(beforeMove);
        expect(screen.getByText("streaming")).toBeInTheDocument();
        expect(canvas).toHaveAttribute("width", "2340");
        expect(canvas).toHaveAttribute("height", "1080");
        expect(frame.close).toHaveBeenCalled();
        expect(FakeSocket.current.send).toHaveBeenCalledWith(
            JSON.stringify({
                type: "pointer",
                action: "cancel",
                x: 0,
                y: 0,
                width: 2340,
                height: 1080,
                pressure: 0,
                buttons: 0,
            }),
        );
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("stops decoder and releases ownership when the tab is suspended", async () => {
        const { view, act } = await connected();
        fireEvent.click(
            screen.getByRole("button", { name: "Request control" }),
        );
        await screen.findByRole("button", { name: "Release control" });
        const hidden = vi
            .spyOn(document, "hidden", "get")
            .mockReturnValue(true);
        act(() => document.dispatchEvent(new Event("visibilitychange")));
        expect(FakeSocket.current.close).toHaveBeenCalled();
        expect(FakeDecoder.current.close).toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
        expect(screen.getByRole("alert")).toHaveTextContent("tab was hidden");
        hidden.mockRestore();
        view.unmount();
        vi.unstubAllGlobals();
    });
    it("requests fullscreen and reports a rejected fullscreen request", async () => {
        const { view } = await connected();
        HTMLElement.prototype.requestFullscreen = vi.fn(async () => {
            throw new Error("blocked");
        });
        fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
        await screen.findByText("Fullscreen is unavailable.");
        expect(HTMLElement.prototype.requestFullscreen).toHaveBeenCalled();
        view.unmount();
        vi.unstubAllGlobals();
    });
});
