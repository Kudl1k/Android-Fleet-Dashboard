import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    ArrowUp,
    Copy,
    Download,
    Eye,
    File as FileIcon,
    FilePlus2,
    Folder,
    FolderPlus,
    FolderUp,
    Link2,
    Pencil,
    RefreshCw,
    Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { FieldLabel } from "@/components/ui/field";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import ListRegion from "../../components/ListRegion";
import StatusChip from "../../components/StatusChip";
import Confirmation from "../management/Confirmation";
import { useAuth } from "../../lib/auth";
import {
    downloadFile,
    droppedFiles,
    fileApi,
    formatBytes,
    joinPath,
    parentPath,
    pickedFiles,
    sendFile,
    type FileEntry,
    type QueuedFile,
} from "./fileApi";
import "./files.css";

const PARALLEL_UPLOADS = 3;

interface Transfer {
    files: QueuedFile[];
    total: number;
    destination: string;
    overwrite: boolean;
    phase:
        | "ready"
        | "uploading"
        | "conflict"
        | "transferring"
        | "completed"
        | "failed"
        | "cancelled";
    sent: number;
    id?: string;
    error?: string;
}

type Dialogs =
    | { kind: "folder" }
    | { kind: "rename"; entry: FileEntry }
    | { kind: "delete"; entry: FileEntry }
    | { kind: "preview"; entry: FileEntry };

export default function FileManager({
    deviceId,
    online,
    active,
}: {
    deviceId: string;
    online: boolean;
    active: boolean;
}) {
    const auth = useAuth();
    const client = useQueryClient();
    const canRead = auth.can("files.read");
    const canWrite = auth.can("files.write");
    const [path, setPath] = useState<string | null>(null);
    const [typed, setTyped] = useState("");
    const [dialog, setDialog] = useState<Dialogs | null>(null);
    const [notice, setNotice] = useState("");
    const [actionError, setActionError] = useState("");
    const [transfer, setTransfer] = useState<Transfer | null>(null);
    const [dragging, setDragging] = useState(false);
    const abort = useRef<AbortController | null>(null);
    const filesInput = useRef<HTMLInputElement | null>(null);
    const folderInput = useRef<HTMLInputElement | null>(null);
    const enabled = active && online && canRead;

    const places = useQuery({
        queryKey: ["files", deviceId, "locations"],
        queryFn: () => fileApi.locations(deviceId),
        enabled,
        staleTime: 60_000,
    });
    const current = path ?? places.data?.locations[0]?.path ?? null;
    const listing = useQuery({
        queryKey: ["files", deviceId, "list", current],
        queryFn: () => fileApi.list(deviceId, current as string),
        enabled: enabled && current !== null,
    });
    useEffect(() => setTyped(current ?? ""), [current]);
    // A tab switch keeps the upload alive; leaving the device page stops it.
    useEffect(() => () => abort.current?.abort(), []);

    const refresh = () =>
        client.invalidateQueries({ queryKey: ["files", deviceId, "list"] });
    const open = (next: string) => {
        setNotice("");
        setActionError("");
        setPath(next);
    };
    async function act(work: () => Promise<unknown>, done: string) {
        setActionError("");
        try {
            await work();
            setNotice(done);
            setDialog(null);
            await refresh();
        } catch (error) {
            setActionError((error as Error).message);
        }
    }

    function queue(files: QueuedFile[]) {
        if (!files.length || !current) return;
        setNotice("");
        setTransfer({
            files,
            total: files.reduce((sum, item) => sum + item.file.size, 0),
            destination: current,
            overwrite: false,
            phase: "ready",
            sent: 0,
        });
    }

    async function follow(id: string) {
        for (;;) {
            await new Promise((resolve) => setTimeout(resolve, 1000));
            if (abort.current?.signal.aborted) return;
            let status;
            try {
                status = await fileApi.status(id);
            } catch (error) {
                setTransfer(
                    (t) =>
                        t && {
                            ...t,
                            phase: "failed",
                            error: (error as Error).message,
                        },
                );
                return;
            }
            if (status.state === "transferring") continue;
            setTransfer(
                (t) =>
                    t && {
                        ...t,
                        phase:
                            status.state === "completed"
                                ? "completed"
                                : status.state === "cancelled"
                                  ? "cancelled"
                                  : "failed",
                        error: status.error ?? undefined,
                    },
            );
            if (status.state === "completed") await refresh();
            return;
        }
    }

    async function commit(t: Transfer, id: string, overwrite: boolean) {
        try {
            await fileApi.commit(id, t.destination, overwrite);
        } catch (error) {
            const conflict = (error as { status?: number }).status === 409;
            setTransfer(
                (s) =>
                    s && {
                        ...s,
                        phase: conflict ? "conflict" : "failed",
                        error: (error as Error).message,
                    },
            );
            return;
        }
        setTransfer(
            (s) => s && { ...s, phase: "transferring", error: undefined },
        );
        await follow(id);
    }

    async function start(t: Transfer) {
        const controller = new AbortController();
        abort.current = controller;
        setTransfer({ ...t, phase: "uploading", sent: 0, error: undefined });
        let id: string | undefined;
        try {
            id = (await fileApi.createUpload(deviceId)).id;
            setTransfer((s) => s && { ...s, id });
            const progress = new Map<string, number>();
            const report = () =>
                setTransfer(
                    (s) =>
                        s && {
                            ...s,
                            sent: [...progress.values()].reduce(
                                (a, b) => a + b,
                                0,
                            ),
                        },
                );
            const pending = [...t.files];
            const worker = async () => {
                for (let item = pending.shift(); item; item = pending.shift()) {
                    const current = item;
                    await sendFile(
                        id as string,
                        current,
                        (sent) => {
                            progress.set(current.path, sent);
                            report();
                        },
                        controller.signal,
                    );
                }
            };
            await Promise.all(Array.from({ length: PARALLEL_UPLOADS }, worker));
        } catch (error) {
            if (id) void fileApi.cancel(id).catch(() => undefined);
            const cancelled = (error as Error).name === "AbortError";
            setTransfer(
                (s) =>
                    s && {
                        ...s,
                        phase: cancelled ? "cancelled" : "failed",
                        error: cancelled ? undefined : (error as Error).message,
                    },
            );
            return;
        }
        await commit(t, id, t.overwrite);
    }

    async function cancelTransfer() {
        abort.current?.abort();
        if (transfer?.id && transfer.phase !== "uploading")
            await fileApi.cancel(transfer.id).catch(() => undefined);
        setTransfer((s) => s && { ...s, phase: "cancelled" });
    }

    if (!canRead)
        return (
            <p className="muted">
                Your access does not include the device file manager.
            </p>
        );
    if (!online)
        return (
            <p className="muted">
                Files are available while the device is connected.
            </p>
        );

    const entries = listing.data?.entries ?? [];
    const writable = canWrite && !!listing.data?.writable;
    const busy =
        transfer?.phase === "uploading" || transfer?.phase === "transferring";
    const crumbs = (current ?? "/")
        .split("/")
        .filter(Boolean)
        .map((part, index, all) => ({
            name: part,
            path: "/" + all.slice(0, index + 1).join("/"),
        }));

    return (
        <div className="file-manager">
            <nav className="file-locations" aria-label="Device locations">
                {places.data?.locations.map((place) => (
                    <Button
                        key={place.path}
                        variant="outline"
                        aria-pressed={current === place.path}
                        onClick={() => open(place.path)}
                    >
                        {place.label}
                    </Button>
                ))}
                {places.isError && (
                    <span role="alert" className="error">
                        {places.error.message}
                    </span>
                )}
            </nav>
            <form
                className="file-path-bar"
                onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    if (typed.trim()) open(typed.trim());
                }}
            >
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label="Parent folder"
                    disabled={!current || current === "/"}
                    onClick={() => current && open(parentPath(current))}
                >
                    <ArrowUp aria-hidden="true" />
                </Button>
                <label className="file-path-field">
                    <span className="sr-only">Device path</span>
                    <Input
                        className="mono"
                        value={typed}
                        onChange={(event) => setTyped(event.target.value)}
                        spellCheck={false}
                        autoComplete="off"
                    />
                </label>
                <Button type="submit" variant="outline">
                    Go
                </Button>
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label="Refresh folder"
                    aria-busy={listing.isFetching}
                    onClick={() => void refresh()}
                >
                    <RefreshCw aria-hidden="true" />
                </Button>
            </form>
            <nav className="file-breadcrumbs mono" aria-label="Current folder">
                <button type="button" onClick={() => open("/")}>
                    /
                </button>
                {crumbs.map((crumb, index) => (
                    <span key={crumb.path}>
                        {index > 0 && <span aria-hidden="true">/</span>}
                        <button
                            type="button"
                            aria-current={
                                index === crumbs.length - 1 ? "page" : undefined
                            }
                            onClick={() => open(crumb.path)}
                        >
                            {crumb.name}
                        </button>
                    </span>
                ))}
            </nav>
            {canWrite && (
                <div className="actions device-actions file-toolbar">
                    <Button
                        variant="outline"
                        disabled={!writable}
                        onClick={() => setDialog({ kind: "folder" })}
                    >
                        <FolderPlus
                            data-icon="inline-start"
                            aria-hidden="true"
                        />
                        New folder
                    </Button>
                    <Button
                        variant="outline"
                        disabled={!writable || busy}
                        onClick={() => filesInput.current?.click()}
                    >
                        <FilePlus2
                            data-icon="inline-start"
                            aria-hidden="true"
                        />
                        Upload files
                    </Button>
                    <Button
                        variant="outline"
                        disabled={!writable || busy}
                        onClick={() => folderInput.current?.click()}
                    >
                        <FolderUp data-icon="inline-start" aria-hidden="true" />
                        Upload folder
                    </Button>
                    <input
                        ref={filesInput}
                        type="file"
                        multiple
                        hidden
                        data-upload="files"
                        onChange={(event) => {
                            queue(pickedFiles(event.target.files));
                            event.target.value = "";
                        }}
                    />
                    <input
                        ref={(input) => {
                            folderInput.current = input;
                            // Not in React's typings; enables folder selection.
                            input?.setAttribute("webkitdirectory", "");
                        }}
                        type="file"
                        hidden
                        data-upload="folder"
                        onChange={(event) => {
                            queue(pickedFiles(event.target.files));
                            event.target.value = "";
                        }}
                    />
                    {listing.data && !listing.data.writable && (
                        <span className="muted">
                            This folder is read-only here. Uploads go to shared
                            storage, device temp or the Termux home.
                        </span>
                    )}
                </div>
            )}
            {transfer && (
                <TransferPanel
                    transfer={transfer}
                    onChange={setTransfer}
                    onStart={() => void start(transfer)}
                    onReplace={() => {
                        if (!transfer.id) return;
                        const next = { ...transfer, overwrite: true };
                        setTransfer({ ...next, phase: "transferring" });
                        void commit(next, transfer.id, true);
                    }}
                    onCancel={() => void cancelTransfer()}
                    onClose={() => setTransfer(null)}
                />
            )}
            {notice && (
                <p role="status" className="file-notice">
                    {notice}
                </p>
            )}
            {actionError && !dialog && (
                <p role="alert" className="error">
                    {actionError}
                </p>
            )}
            <div
                className="file-drop"
                data-dragging={dragging || undefined}
                onDragOver={(event) => {
                    if (!writable || busy) return;
                    event.preventDefault();
                    setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                    if (!writable || busy) return;
                    event.preventDefault();
                    setDragging(false);
                    void droppedFiles(event.dataTransfer.items).then(queue);
                }}
            >
                <div className="device-list-heading">
                    <h3 className="mono file-heading">{current ?? "…"}</h3>
                    <span className="muted">
                        {listing.isSuccess &&
                            `${entries.length} items${writable ? " · drop files here to upload" : ""}`}
                    </span>
                </div>
                {listing.isPending && current && (
                    <p role="status" className="muted">
                        Loading folder…
                    </p>
                )}
                {listing.isError && (
                    <Alert variant="destructive">
                        <AlertTitle>Folder unavailable</AlertTitle>
                        <AlertDescription>
                            {listing.error.message}
                        </AlertDescription>
                    </Alert>
                )}
                {listing.isSuccess && !entries.length && (
                    <p className="muted list-empty">This folder is empty.</p>
                )}
                {entries.length > 0 && (
                    <ListRegion label="Folder contents" className="file-table">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead scope="col">Name</TableHead>
                                    <TableHead scope="col" className="numeric">
                                        Size
                                    </TableHead>
                                    <TableHead scope="col">Modified</TableHead>
                                    <TableHead scope="col">Actions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {entries.map((entry) => (
                                    <EntryRow
                                        key={entry.path}
                                        entry={entry}
                                        writable={writable}
                                        onOpen={() => open(entry.path)}
                                        onDialog={setDialog}
                                        onDownload={() =>
                                            void downloadFile(
                                                deviceId,
                                                entry,
                                            ).catch((error: Error) =>
                                                setActionError(error.message),
                                            )
                                        }
                                        onCopy={(text, what) =>
                                            void navigator.clipboard
                                                ?.writeText(text)
                                                .then(() =>
                                                    setNotice(`${what} copied`),
                                                )
                                        }
                                    />
                                ))}
                            </TableBody>
                        </Table>
                    </ListRegion>
                )}
            </div>
            {dialog?.kind === "folder" && current && (
                <NameDialog
                    title="New folder"
                    description={`Create a folder in ${current}.`}
                    initial=""
                    action="Create folder"
                    error={actionError}
                    onCancel={() => {
                        setDialog(null);
                        setActionError("");
                    }}
                    onSubmit={(name) =>
                        act(
                            () =>
                                fileApi.mkdir(
                                    deviceId,
                                    joinPath(current, name),
                                ),
                            `Folder ${name} created`,
                        )
                    }
                />
            )}
            {dialog?.kind === "rename" && (
                <NameDialog
                    title="Rename"
                    description={`Rename ${dialog.entry.path}.`}
                    initial={dialog.entry.name}
                    action="Rename"
                    error={actionError}
                    onCancel={() => {
                        setDialog(null);
                        setActionError("");
                    }}
                    onSubmit={(name) =>
                        act(
                            () =>
                                fileApi.rename(
                                    deviceId,
                                    dialog.entry.path,
                                    name,
                                ),
                            `Renamed to ${name}`,
                        )
                    }
                />
            )}
            {dialog?.kind === "delete" && (
                <Confirmation
                    title={`Remove ${dialog.entry.name}?`}
                    onCancel={() => {
                        setDialog(null);
                        setActionError("");
                    }}
                >
                    <p>
                        <span className="mono">{dialog.entry.path}</span>{" "}
                        {dialog.entry.kind === "directory"
                            ? "and everything inside it will be permanently removed from the device."
                            : "will be permanently removed from the device."}
                    </p>
                    {actionError && (
                        <p role="alert" className="error">
                            {actionError}
                        </p>
                    )}
                    <div className="actions device-dialog-actions">
                        <Button
                            variant="outline"
                            autoFocus
                            onClick={() => {
                                setDialog(null);
                                setActionError("");
                            }}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() =>
                                void act(
                                    () =>
                                        fileApi.remove(
                                            deviceId,
                                            dialog.entry.path,
                                        ),
                                    `${dialog.entry.name} removed`,
                                )
                            }
                        >
                            Remove
                        </Button>
                    </div>
                </Confirmation>
            )}
            {dialog?.kind === "preview" && (
                <PreviewDialog
                    deviceId={deviceId}
                    entry={dialog.entry}
                    onClose={() => setDialog(null)}
                />
            )}
        </div>
    );
}

function EntryRow({
    entry,
    writable,
    onOpen,
    onDialog,
    onDownload,
    onCopy,
}: {
    entry: FileEntry;
    writable: boolean;
    onOpen: () => void;
    onDialog: (dialog: Dialogs) => void;
    onDownload: () => void;
    onCopy: (text: string, what: string) => void;
}) {
    const folderLike = entry.kind === "directory" || entry.kind === "symlink";
    const Icon =
        entry.kind === "directory"
            ? Folder
            : entry.kind === "symlink"
              ? Link2
              : FileIcon;
    return (
        <TableRow>
            <TableCell>
                <span className="device-cell-label" aria-hidden="true">
                    Name
                </span>
                <span className="file-name">
                    <Icon size={16} aria-hidden="true" />
                    {folderLike ? (
                        <button type="button" onClick={onOpen}>
                            {entry.name}
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={() => onDialog({ kind: "preview", entry })}
                        >
                            {entry.name}
                        </button>
                    )}
                    <span className="file-mode mono">
                        {entry.mode} · {entry.owner}
                    </span>
                </span>
            </TableCell>
            <TableCell className="numeric">
                <span className="device-cell-label" aria-hidden="true">
                    Size
                </span>
                {entry.kind === "file" ? formatBytes(entry.size) : "—"}
            </TableCell>
            <TableCell>
                <span className="device-cell-label" aria-hidden="true">
                    Modified
                </span>
                {entry.modified
                    ? new Date(entry.modified * 1000).toLocaleString()
                    : "—"}
            </TableCell>
            <TableCell>
                <span className="device-cell-label" aria-hidden="true">
                    Actions
                </span>
                <div className="file-row-actions">
                    {entry.kind === "file" && (
                        <>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Preview ${entry.name}`}
                                onClick={() =>
                                    onDialog({ kind: "preview", entry })
                                }
                            >
                                <Eye aria-hidden="true" />
                            </Button>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Download ${entry.name}`}
                                onClick={onDownload}
                            >
                                <Download aria-hidden="true" />
                            </Button>
                        </>
                    )}
                    <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Copy path of ${entry.name}`}
                        onClick={() => onCopy(entry.path, "Path")}
                    >
                        <Copy aria-hidden="true" />
                    </Button>
                    {writable && (
                        <>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Rename ${entry.name}`}
                                onClick={() =>
                                    onDialog({ kind: "rename", entry })
                                }
                            >
                                <Pencil aria-hidden="true" />
                            </Button>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Remove ${entry.name}`}
                                onClick={() =>
                                    onDialog({ kind: "delete", entry })
                                }
                            >
                                <Trash2 aria-hidden="true" />
                            </Button>
                        </>
                    )}
                </div>
            </TableCell>
        </TableRow>
    );
}

function TransferPanel({
    transfer,
    onChange,
    onStart,
    onReplace,
    onCancel,
    onClose,
}: {
    transfer: Transfer;
    onChange: (transfer: Transfer) => void;
    onStart: () => void;
    onReplace: () => void;
    onCancel: () => void;
    onClose: () => void;
}) {
    const { phase } = transfer;
    const percent = transfer.total
        ? Math.min(100, Math.round((transfer.sent / transfer.total) * 100))
        : 100;
    const chip = {
        ready: ["queued", "Ready"],
        uploading: ["running", `Uploading ${percent}%`],
        conflict: ["warning", "Already exists"],
        transferring: ["running", "Copying to device"],
        completed: ["succeeded", "Uploaded"],
        failed: ["failed", "Failed"],
        cancelled: ["cancelled", "Cancelled"],
    }[phase];
    const folders = new Set(
        transfer.files
            .map((item) => item.path.split("/"))
            .filter((parts) => parts.length > 1)
            .map((parts) => parts[0]),
    );
    return (
        <section className="file-transfer" aria-label="Upload">
            <div className="file-transfer-head">
                <div>
                    <strong>
                        {transfer.files.length} files ·{" "}
                        {formatBytes(transfer.total)}
                    </strong>
                    <span className="muted">
                        {folders.size > 0 && `${[...folders].join(", ")} → `}
                        <span className="mono">{transfer.destination}</span>
                    </span>
                </div>
                <StatusChip value={chip[0]} label={chip[1]} />
            </div>
            {(phase === "uploading" || phase === "transferring") && (
                <progress
                    className="file-progress"
                    max={100}
                    value={phase === "uploading" ? percent : undefined}
                    aria-label={
                        phase === "uploading"
                            ? `Uploading to the manager, ${percent}%`
                            : "Copying to the device"
                    }
                />
            )}
            {phase === "transferring" && (
                <p className="muted">
                    The manager is copying the files to the phone. Large folders
                    take a while over Wi-Fi.
                </p>
            )}
            {transfer.error && (
                <p role="alert" className="error">
                    {transfer.error}
                </p>
            )}
            <div className="actions device-actions">
                {phase === "ready" && (
                    <>
                        <FieldLabel className="file-overwrite">
                            <Checkbox
                                checked={transfer.overwrite}
                                onCheckedChange={(checked) =>
                                    onChange({
                                        ...transfer,
                                        overwrite: checked === true,
                                    })
                                }
                            />
                            Replace existing items with the same name
                        </FieldLabel>
                        <Button onClick={onStart}>Upload</Button>
                        <Button variant="outline" onClick={onClose}>
                            Discard
                        </Button>
                    </>
                )}
                {phase === "conflict" && (
                    <>
                        <Button variant="destructive" onClick={onReplace}>
                            Replace existing
                        </Button>
                        <Button variant="outline" onClick={onCancel}>
                            Cancel upload
                        </Button>
                    </>
                )}
                {(phase === "uploading" || phase === "transferring") && (
                    <Button variant="outline" onClick={onCancel}>
                        Cancel upload
                    </Button>
                )}
                {(phase === "completed" ||
                    phase === "failed" ||
                    phase === "cancelled") && (
                    <Button variant="outline" onClick={onClose}>
                        Close
                    </Button>
                )}
            </div>
        </section>
    );
}

function NameDialog({
    title,
    description,
    initial,
    action,
    error,
    onCancel,
    onSubmit,
}: {
    title: string;
    description: string;
    initial: string;
    action: string;
    error: string;
    onCancel: () => void;
    onSubmit: (name: string) => Promise<void>;
}) {
    const [name, setName] = useState(initial);
    const [pending, setPending] = useState(false);
    const invalid = !name.trim() || name.includes("/");
    return (
        <Dialog open onOpenChange={(open) => !open && onCancel()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>{description}</DialogDescription>
                </DialogHeader>
                <form
                    className="file-name-form"
                    onSubmit={async (event) => {
                        event.preventDefault();
                        if (invalid || pending) return;
                        setPending(true);
                        await onSubmit(name.trim());
                        setPending(false);
                    }}
                >
                    <label>
                        Name
                        <Input
                            autoFocus
                            value={name}
                            aria-invalid={!!error || undefined}
                            onChange={(event) => setName(event.target.value)}
                        />
                    </label>
                    {error && (
                        <p role="alert" className="error">
                            {error}
                        </p>
                    )}
                    <div className="actions device-dialog-actions">
                        <Button
                            type="button"
                            variant="outline"
                            onClick={onCancel}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="submit"
                            disabled={invalid || pending}
                            aria-busy={pending}
                        >
                            {action}
                        </Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function PreviewDialog({
    deviceId,
    entry,
    onClose,
}: {
    deviceId: string;
    entry: FileEntry;
    onClose: () => void;
}) {
    const preview = useQuery({
        queryKey: ["files", deviceId, "preview", entry.path],
        queryFn: () => fileApi.preview(deviceId, entry.path),
        gcTime: 0,
    });
    return (
        <Dialog open onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="file-preview-dialog">
                <DialogHeader>
                    <DialogTitle>{entry.name}</DialogTitle>
                    <DialogDescription className="mono">
                        {entry.path} · {formatBytes(entry.size)}
                    </DialogDescription>
                </DialogHeader>
                {preview.isPending && (
                    <p role="status" className="muted">
                        Loading preview…
                    </p>
                )}
                {preview.isError && (
                    <p role="alert" className="error">
                        {preview.error.message}
                    </p>
                )}
                {preview.data?.binary && (
                    <p className="muted">
                        This looks like a binary file. Download it to open it
                        locally.
                    </p>
                )}
                {preview.data && !preview.data.binary && (
                    <>
                        {preview.data.truncated && (
                            <p className="muted">
                                Showing the first 256 KiB. Download the file for
                                the full content.
                            </p>
                        )}
                        <pre className="file-preview" tabIndex={0}>
                            {preview.data.content}
                        </pre>
                    </>
                )}
                <div className="actions device-dialog-actions">
                    <Button
                        variant="outline"
                        onClick={() =>
                            void downloadFile(deviceId, entry).catch(
                                () => undefined,
                            )
                        }
                    >
                        <Download data-icon="inline-start" aria-hidden="true" />
                        Download
                    </Button>
                    <Button onClick={onClose}>Close</Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
