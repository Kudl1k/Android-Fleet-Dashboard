import { ApiError, getControlToken, request } from "../../lib/api";

export interface FileEntry {
    name: string;
    path: string;
    kind: "directory" | "file" | "symlink" | "other";
    size: number;
    modified: number;
    mode: string;
    owner: string;
    group: string;
}
export interface Listing {
    path: string;
    writable: boolean;
    entries: FileEntry[];
}
export interface Location {
    label: string;
    path: string;
    writable: boolean;
}
export interface Preview {
    path: string;
    size: number;
    truncated: boolean;
    binary: boolean;
    content: string;
}
export interface UploadStatus {
    id: string;
    state: "receiving" | "transferring" | "completed" | "failed" | "cancelled";
    files: number;
    bytes: number;
    destination: string | null;
    error: string | null;
    max_bytes?: number;
    max_files?: number;
}
/** One file to upload, with its path relative to the chosen destination. */
export interface QueuedFile {
    file: File;
    path: string;
}

const device = (id: string) =>
    `/api/v1/devices/${encodeURIComponent(id)}/files`;

export const fileApi = {
    locations: (id: string) =>
        request<{ root: boolean; locations: Location[] }>(
            `${device(id)}/locations`,
        ),
    list: (id: string, path: string) =>
        request<Listing>(`${device(id)}?path=${encodeURIComponent(path)}`),
    preview: (id: string, path: string) =>
        request<Preview>(
            `${device(id)}/preview?path=${encodeURIComponent(path)}`,
        ),
    mkdir: (id: string, path: string) =>
        request<{ path: string }>(`${device(id)}/folders`, {
            method: "POST",
            body: JSON.stringify({ path }),
        }),
    rename: (id: string, path: string, name: string) =>
        request<{ path: string }>(`${device(id)}/rename`, {
            method: "POST",
            body: JSON.stringify({ path, name }),
        }),
    remove: (id: string, path: string) =>
        request<{ status: string }>(`${device(id)}/delete`, {
            method: "POST",
            body: JSON.stringify({ path, confirmed: true }),
        }),
    createUpload: (id: string) =>
        request<UploadStatus>(`${device(id)}/uploads`, { method: "POST" }),
    commit: (upload: string, destination: string, overwrite: boolean) =>
        request<UploadStatus>(
            `/api/v1/files/uploads/${encodeURIComponent(upload)}/commit`,
            {
                method: "POST",
                body: JSON.stringify({ destination, overwrite }),
            },
        ),
    status: (upload: string) =>
        request<UploadStatus>(
            `/api/v1/files/uploads/${encodeURIComponent(upload)}`,
        ),
    cancel: (upload: string) =>
        request<{ status: string }>(
            `/api/v1/files/uploads/${encodeURIComponent(upload)}`,
            { method: "DELETE" },
        ),
};

/** PUT one file with progress; fetch cannot report upload progress. */
export function sendFile(
    upload: string,
    item: QueuedFile,
    onProgress: (sent: number) => void,
    signal: AbortSignal,
): Promise<void> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(
            "PUT",
            `/api/v1/files/uploads/${encodeURIComponent(upload)}/content?path=${encodeURIComponent(item.path)}`,
        );
        const token = getControlToken();
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.setRequestHeader("Content-Type", "application/octet-stream");
        xhr.upload.onprogress = (event) => onProgress(event.loaded);
        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                onProgress(item.file.size);
                resolve();
                return;
            }
            let message = `Upload failed (${xhr.status}).`;
            try {
                const body = JSON.parse(xhr.responseText);
                message =
                    body?.error?.message ??
                    (typeof body?.detail === "string" ? body.detail : message);
            } catch {
                // Proxies answer with HTML; keep the status message.
            }
            if (xhr.status === 413 && !message.includes("MiB"))
                message = "The file is larger than the upload limit.";
            reject(new ApiError(xhr.status, message));
        };
        xhr.onerror = () =>
            reject(new ApiError(0, "The upload connection was interrupted."));
        xhr.onabort = () =>
            reject(new DOMException("Upload cancelled", "AbortError"));
        signal.addEventListener("abort", () => xhr.abort(), { once: true });
        xhr.send(item.file);
    });
}

/** Download a device file through the authenticated API and save it locally. */
export async function downloadFile(id: string, entry: FileEntry) {
    const token = getControlToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(
        `${device(id)}/download?path=${encodeURIComponent(entry.path)}`,
        { headers, credentials: "omit" },
    );
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(
            response.status,
            body?.error?.message ??
                (typeof body?.detail === "string"
                    ? body.detail
                    : `Download failed (${response.status}).`),
        );
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = entry.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Files dropped onto the browser, including the contents of dropped folders. */
export async function droppedFiles(
    items: DataTransferItemList,
): Promise<QueuedFile[]> {
    const entries = Array.from(items)
        .map((item) => item.webkitGetAsEntry?.())
        .filter((entry): entry is FileSystemEntry => !!entry);
    const result: QueuedFile[] = [];
    async function walk(entry: FileSystemEntry, prefix: string) {
        const path = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.isFile) {
            const file = await new Promise<File>((resolve, reject) =>
                (entry as FileSystemFileEntry).file(resolve, reject),
            );
            result.push({ file, path });
            return;
        }
        const reader = (entry as FileSystemDirectoryEntry).createReader();
        // readEntries returns results in batches until it yields an empty one.
        for (;;) {
            const batch = await new Promise<FileSystemEntry[]>(
                (resolve, reject) => reader.readEntries(resolve, reject),
            );
            if (!batch.length) break;
            for (const child of batch) await walk(child, path);
        }
    }
    for (const entry of entries) await walk(entry, "");
    return result;
}

/** Files chosen with a file or folder picker. */
export function pickedFiles(files: FileList | null): QueuedFile[] {
    return Array.from(files ?? []).map((file) => ({
        file,
        path: file.webkitRelativePath || file.name,
    }));
}

export function formatBytes(bytes: number) {
    const units = ["B", "KiB", "MiB", "GiB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${unit ? value.toFixed(1) : value} ${units[unit]}`;
}

export function joinPath(directory: string, name: string) {
    return directory === "/" ? `/${name}` : `${directory}/${name}`;
}

export function parentPath(path: string) {
    const index = path.lastIndexOf("/");
    return index <= 0 ? "/" : path.slice(0, index);
}
