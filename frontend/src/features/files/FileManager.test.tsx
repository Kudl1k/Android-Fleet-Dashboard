import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import FileManager from "./FileManager";
import { request } from "../../lib/api";
import { sendFile } from "./fileApi";

const auth = {
    permissions: ["files.read", "files.write"],
    can: (permission: string) => auth.permissions.includes(permission),
};
vi.mock("../../lib/auth", () => ({ useAuth: () => auth }));
vi.mock("../../lib/api", () => {
    class ApiError extends Error {
        constructor(
            public status: number,
            message: string,
        ) {
            super(message);
        }
    }
    return { request: vi.fn(), getControlToken: () => "t", ApiError };
});
vi.mock("./fileApi", async (original) => ({
    ...(await original<typeof import("./fileApi")>()),
    sendFile: vi.fn(
        async (
            _id: string,
            item: { file: File },
            progress: (n: number) => void,
        ) => progress(item.file.size),
    ),
}));

const entry = (name: string, kind = "file", size = 12) => ({
    name,
    path: `/sdcard/${name}`,
    kind,
    size,
    modified: 1_700_000_000,
    mode: kind === "directory" ? "drwxrwx---" : "-rw-rw----",
    owner: "root",
    group: "everybody",
});
let conflictOnce = false;
let state = "completed";

function show(props: Partial<Parameters<typeof FileManager>[0]> = {}) {
    render(
        <QueryClientProvider
            client={
                new QueryClient({
                    defaultOptions: { queries: { retry: false } },
                })
            }
        >
            <FileManager deviceId="d1" online active {...props} />
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    auth.permissions = ["files.read", "files.write"];
    conflictOnce = false;
    state = "completed";
    vi.mocked(request).mockImplementation(async (path, options) => {
        const url = new URL(path, "http://x");
        if (url.pathname.endsWith("/locations"))
            return {
                root: true,
                locations: [
                    {
                        label: "Shared storage",
                        path: "/sdcard",
                        writable: true,
                    },
                    {
                        label: "Termux home",
                        path: "/data/data/com.termux/files/home",
                        writable: true,
                    },
                ],
            };
        if (url.pathname === "/api/v1/devices/d1/files")
            return {
                path: url.searchParams.get("path"),
                writable: true,
                entries:
                    url.searchParams.get("path") === "/sdcard"
                        ? [
                              entry("Download", "directory", 4096),
                              entry("run.py"),
                          ]
                        : [],
            };
        if (url.pathname.endsWith("/preview"))
            return {
                path: "/sdcard/run.py",
                size: 12,
                truncated: false,
                binary: false,
                content: "print('hi')",
            };
        if (url.pathname.endsWith("/uploads"))
            return { id: "u1", state: "receiving" };
        if (url.pathname.endsWith("/commit")) {
            if (conflictOnce) {
                conflictOnce = false;
                throw Object.assign(
                    new Error("Already in the destination: final"),
                    {
                        status: 409,
                    },
                );
            }
            return { id: "u1", state: "transferring", options };
        }
        if (url.pathname === "/api/v1/files/uploads/u1")
            return {
                id: "u1",
                state,
                error: state === "failed" ? "Denied" : null,
            };
        return { status: "ok" };
    });
});
afterEach(cleanup);

it("opens the first location and navigates into folders", async () => {
    show();
    expect(await screen.findByText("run.py")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() =>
        expect(request).toHaveBeenCalledWith(
            "/api/v1/devices/d1/files?path=%2Fsdcard%2FDownload",
        ),
    );
    expect(
        await screen.findByText("This folder is empty."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Parent folder" }));
    expect(await screen.findByText("run.py")).toBeInTheDocument();
});

it("does not load files until the tab is opened", () => {
    show({ active: false });
    expect(request).not.toHaveBeenCalled();
});

it("hides changes without write access", async () => {
    auth.permissions = ["files.read"];
    show();
    await screen.findByText("run.py");
    expect(screen.queryByText("Upload files")).not.toBeInTheDocument();
    expect(
        screen.queryByRole("button", { name: "Remove run.py" }),
    ).not.toBeInTheDocument();
    expect(
        screen.getByRole("button", { name: "Copy path of run.py" }),
    ).toBeInTheDocument();
});

it("previews a text file", async () => {
    show();
    fireEvent.click(
        await screen.findByRole("button", { name: "Preview run.py" }),
    );
    expect(await screen.findByText("print('hi')")).toBeInTheDocument();
});

it("removes an item only after confirmation", async () => {
    show();
    fireEvent.click(
        await screen.findByRole("button", { name: "Remove run.py" }),
    );
    expect(request).not.toHaveBeenCalledWith(
        "/api/v1/devices/d1/files/delete",
        expect.anything(),
    );
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
        expect(request).toHaveBeenCalledWith(
            "/api/v1/devices/d1/files/delete",
            {
                method: "POST",
                body: JSON.stringify({
                    path: "/sdcard/run.py",
                    confirmed: true,
                }),
            },
        ),
    );
    expect(await screen.findByText("run.py removed")).toBeInTheDocument();
});

function pickFolder() {
    const input = document.querySelector(
        "input[data-upload=folder]",
    ) as HTMLInputElement;
    const file = new File(["model"], "model.bin");
    Object.defineProperty(file, "webkitRelativePath", {
        value: "final/model.bin",
    });
    fireEvent.change(input, { target: { files: [file] } });
}

it("uploads a folder in one staged transfer", async () => {
    show();
    await screen.findByText("run.py");
    pickFolder();
    expect(await screen.findByText("1 files · 5 B")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(
        await screen.findByText("Uploaded", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(vi.mocked(sendFile).mock.calls[0][1].path).toBe("final/model.bin");
    expect(request).toHaveBeenCalledWith("/api/v1/files/uploads/u1/commit", {
        method: "POST",
        body: JSON.stringify({ destination: "/sdcard", overwrite: false }),
    });
});

it("asks before replacing existing items", async () => {
    conflictOnce = true;
    show();
    await screen.findByText("run.py");
    pickFolder();
    fireEvent.click(await screen.findByRole("button", { name: "Upload" }));
    expect(
        await screen.findByText("Already in the destination: final"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Replace existing" }));
    await waitFor(() =>
        expect(request).toHaveBeenCalledWith(
            "/api/v1/files/uploads/u1/commit",
            {
                method: "POST",
                body: JSON.stringify({
                    destination: "/sdcard",
                    overwrite: true,
                }),
            },
        ),
    );
    expect(
        await screen.findByText("Uploaded", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
});

it("reports a transfer the device rejected", async () => {
    state = "failed";
    show();
    await screen.findByText("run.py");
    pickFolder();
    fireEvent.click(await screen.findByRole("button", { name: "Upload" }));
    expect(
        await screen.findByText("Denied", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
});

it("explains why files are unavailable offline", () => {
    show({ online: false });
    expect(
        screen.getByText("Files are available while the device is connected."),
    ).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
});
