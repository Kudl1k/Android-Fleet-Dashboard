import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel, FieldGroup } from "@/components/ui/field";
import {
    Table,
    TableHeader,
    TableRow,
    TableHead,
    TableBody,
    TableCell,
} from "@/components/ui/table";
import { Lock, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import ListRegion from "../../components/ListRegion";
import Confirmation from "../management/Confirmation";
import {
    APP_CHANGES,
    canRemove,
    formatSize,
    matchesFilter,
    parseAppList,
    type AppEntry,
    type AppFilter,
} from "./apps";
import type { Operation } from "./operations";
import "./apps.css";

type Body = { action: string; package?: string; confirmed?: boolean };

const CATEGORY_LABELS: Record<string, string> = {
    removable: "Removable",
    user: "Installed by user",
    protected: "Protected",
    system: "System",
};
const FILTERS: Array<[AppFilter, string]> = [
    ["removable", "Removable"],
    ["user", "Installed by user"],
    ["kept", "Protected & system"],
    ["removed", "Removed"],
    ["all", "All"],
];

export default function ApplicationsPanel({
    list,
    operations,
    online,
    busy,
    allowed,
    submit,
    requestConfirm,
    refreshButton,
}: {
    list: Operation | undefined;
    operations: Operation[];
    online: boolean;
    busy: boolean;
    allowed: (action: string) => boolean;
    submit: (body: Body) => void;
    requestConfirm: (body: { action: string; package?: string }) => void;
    refreshButton: ReactNode;
}) {
    const [search, setSearch] = useState("");
    const [chosenFilter, setFilter] = useState<AppFilter | null>(null);
    const [cleanupOpen, setCleanupOpen] = useState(false);
    const { apps, removed, classified } = parseAppList(list);
    const filter = chosenFilter ?? (classified ? "removable" : "all");
    const query = search.toLowerCase();
    const removable = apps.filter((app) => app.category === "removable");
    const removableBytes = removable.reduce(
        (sum, app) => sum + (app.size_bytes ?? 0),
        0,
    );
    const rows: AppEntry[] =
        filter === "removed"
            ? removed.map((name) => ({ package: name }))
            : apps.filter((app) => matchesFilter(app, filter));
    const visible = rows.filter((app) =>
        app.package.toLowerCase().includes(query),
    );
    const count = (value: AppFilter) =>
        value === "removed"
            ? removed.length
            : apps.filter((app) => matchesFilter(app, value)).length;

    // Re-read the package list once after an operation changed the installed apps.
    const lastChange = operations.find(
        (op) => APP_CHANGES.has(op.action) && op.state === "succeeded",
    );
    const stale = Boolean(
        lastChange && list && lastChange.created_at > list.created_at,
    );
    const refreshedAfter = useRef<string | null>(null);
    useEffect(() => {
        if (
            stale &&
            lastChange &&
            !busy &&
            online &&
            allowed("apps.list") &&
            refreshedAfter.current !== lastChange.id
        ) {
            refreshedAfter.current = lastChange.id;
            submit({ action: "apps.list" });
        }
    }, [stale, lastChange, busy, online, allowed, submit]);

    const cleanup = operations.find((op) => op.action === "apps.cleanup");
    const cleanupResult = cleanup?.result as {
        removed?: string[];
        failed?: string[];
        freed_bytes_estimate?: number;
    } | null;
    const disabled = (action: string) => !online || busy || !allowed(action);

    return (
        <section className="device-applications-panel">
            <div className="device-list-heading">
                <h3>Applications</h3>
                <span className="muted">
                    {visible.length} of {rows.length} loaded
                </span>
            </div>
            {classified && (
                <div className="app-cleanup">
                    <Sparkles size={20} aria-hidden="true" />
                    <div className="app-cleanup-copy">
                        <strong>Clean up phone</strong>
                        <p className="muted">
                            {removable.length
                                ? `Removes ${removable.length} preinstalled ${removable.length === 1 ? "app" : "apps"} the project does not need${removableBytes ? ` (about ${formatSize(removableBytes)})` : ""}. Termux, Magisk, ADB and Android system parts are protected. Removed apps can be restored.`
                                : "No unneeded preinstalled apps are left on this phone."}
                        </p>
                        {cleanup && (
                            <p className="app-cleanup-result" role="status">
                                {cleanup.state === "succeeded" && cleanupResult
                                    ? `Last cleanup removed ${cleanupResult.removed?.length ?? 0} apps${cleanupResult.freed_bytes_estimate ? `, about ${formatSize(cleanupResult.freed_bytes_estimate)} freed` : ""}${cleanupResult.failed?.length ? `; ${cleanupResult.failed.length} could not be removed` : ""}.`
                                    : cleanup.state === "running" ||
                                        cleanup.state === "queued"
                                      ? "Cleaning up…"
                                      : `Last cleanup ${cleanup.state.replaceAll("_", " ")}.`}
                            </p>
                        )}
                    </div>
                    <Button
                        variant="destructive"
                        disabled={disabled("apps.cleanup") || !removable.length}
                        onClick={() => setCleanupOpen(true)}
                    >
                        Clean up phone…
                    </Button>
                </div>
            )}
            {classified && (
                <div
                    className="app-filters"
                    role="group"
                    aria-label="Application filter"
                >
                    {FILTERS.map(([value, label]) => (
                        <Button
                            key={value}
                            variant="ghost"
                            aria-pressed={filter === value}
                            onClick={() => setFilter(value)}
                        >
                            {label}
                            <span className="app-filter-count">
                                {count(value)}
                            </span>
                        </Button>
                    ))}
                </div>
            )}
            <FieldGroup className="actions device-actions device-form-row">
                <Field>
                    <FieldLabel>
                        Search applications
                        <Input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            type="search"
                        />
                    </FieldLabel>
                </Field>
                {refreshButton}
            </FieldGroup>
            <ListRegion
                label="Installed applications"
                className="device-applications"
            >
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead scope="col">Package</TableHead>
                            <TableHead scope="col">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {visible.map((app) => (
                            <TableRow key={app.package}>
                                <TableCell>
                                    <span
                                        className="device-cell-label"
                                        aria-hidden="true"
                                    >
                                        Package
                                    </span>
                                    <span className="app-identity">
                                        <span className="mono">
                                            {app.package}
                                        </span>
                                        {app.category && (
                                            <span className="app-meta">
                                                <Badge
                                                    variant="outline"
                                                    className="app-category"
                                                    data-category={app.category}
                                                >
                                                    {
                                                        CATEGORY_LABELS[
                                                            app.category
                                                        ]
                                                    }
                                                </Badge>
                                                {app.size_bytes ? (
                                                    <span className="muted">
                                                        {formatSize(
                                                            app.size_bytes,
                                                        )}
                                                    </span>
                                                ) : null}
                                            </span>
                                        )}
                                    </span>
                                </TableCell>
                                <TableCell>
                                    <span
                                        className="device-cell-label"
                                        aria-hidden="true"
                                    >
                                        Actions
                                    </span>
                                    {filter === "removed" ? (
                                        <div className="actions device-actions device-package-actions">
                                            <Button
                                                variant="outline"
                                                disabled={disabled(
                                                    "apps.restore",
                                                )}
                                                onClick={() =>
                                                    submit({
                                                        action: "apps.restore",
                                                        package: app.package,
                                                    })
                                                }
                                            >
                                                Restore
                                            </Button>
                                        </div>
                                    ) : (
                                        <PackageActions
                                            app={app}
                                            disabled={disabled}
                                            submit={submit}
                                            requestConfirm={requestConfirm}
                                        />
                                    )}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {visible.length === 0 && (
                    <p className="muted list-empty">
                        {rows.length
                            ? "No applications match this search."
                            : !list
                              ? "Refresh applications to retrieve the installed package list."
                              : filter === "removed"
                                ? "No removed apps. Apps removed here can be restored from this list."
                                : filter === "removable"
                                  ? "Nothing left to clean up."
                                  : "No application records returned."}
                    </p>
                )}
            </ListRegion>
            {cleanupOpen && (
                <Confirmation
                    title="Clean up phone"
                    onCancel={() => setCleanupOpen(false)}
                >
                    <p>
                        These {removable.length} preinstalled apps will be
                        removed together with their data and updates
                        {removableBytes
                            ? ` (about ${formatSize(removableBytes)})`
                            : ""}
                        . They can be restored later from the Removed list.
                    </p>
                    <ul className="app-cleanup-list">
                        {removable.map((app) => (
                            <li key={app.package}>
                                <span className="mono">{app.package}</span>
                                {app.size_bytes ? (
                                    <span className="muted">
                                        {formatSize(app.size_bytes)}
                                    </span>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                    <div className="actions device-dialog-actions">
                        <Button
                            variant="outline"
                            autoFocus
                            onClick={() => setCleanupOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => {
                                submit({
                                    action: "apps.cleanup",
                                    confirmed: true,
                                });
                                setCleanupOpen(false);
                            }}
                        >
                            Remove {removable.length} apps
                        </Button>
                    </div>
                </Confirmation>
            )}
        </section>
    );
}

function PackageActions({
    app,
    disabled,
    submit,
    requestConfirm,
}: {
    app: AppEntry;
    disabled: (action: string) => boolean;
    submit: (body: Body) => void;
    requestConfirm: (body: { action: string; package?: string }) => void;
}) {
    const locked = app.category !== undefined && !canRemove(app);
    return (
        <div className="actions device-actions device-package-actions">
            <div
                className="device-package-group"
                role="group"
                aria-label={`Inspect or launch ${app.package}`}
            >
                {[
                    ["apps.inspect", "Inspect"],
                    ["apps.launch", "Launch"],
                ].map(([action, label]) => (
                    <Button
                        variant="outline"
                        key={action}
                        disabled={disabled(action)}
                        onClick={() => submit({ action, package: app.package })}
                    >
                        {label}
                    </Button>
                ))}
            </div>
            <div
                className="device-package-group device-package-danger"
                role="group"
                aria-label={`Stop or uninstall ${app.package}`}
            >
                <Button
                    variant="destructive"
                    disabled={disabled("apps.stop")}
                    onClick={() =>
                        requestConfirm({
                            action: "apps.stop",
                            package: app.package,
                        })
                    }
                >
                    Force-stop
                </Button>
                {locked ? (
                    <span
                        className="app-locked"
                        title={
                            app.category === "protected"
                                ? "Needed by the project or by Android"
                                : "Part of Android; not on the removable list"
                        }
                    >
                        <Lock size={14} aria-hidden="true" />
                        {app.category === "protected" ? "Protected" : "Kept"}
                    </span>
                ) : (
                    <Button
                        variant="destructive"
                        disabled={disabled("apps.uninstall")}
                        onClick={() =>
                            requestConfirm({
                                action: "apps.uninstall",
                                package: app.package,
                            })
                        }
                    >
                        {app.category === "removable" ? "Remove" : "Uninstall"}
                    </Button>
                )}
            </div>
        </div>
    );
}
