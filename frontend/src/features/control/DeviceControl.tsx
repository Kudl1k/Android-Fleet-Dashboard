import { Separator } from "@/components/ui/separator";
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogDescription,
} from "@/components/ui/dialog";
import Disclosure from "@/components/Disclosure";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    Field,
    FieldLabel,
    FieldError,
    FieldSet,
    FieldLegend,
} from "@/components/ui/field";
import ListRegion from "../../components/ListRegion";
import StateBadge from "../../components/StateBadge";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { protectedImage, request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import Confirmation from "../management/Confirmation";
import ApplicationsPanel from "./ApplicationsPanel";
import {
    active,
    operationPermission,
    useOperations,
    type Operation,
} from "./operations";
export default function DeviceControl(props: { id: string; online: boolean }) {
    const auth = useAuth();
    return (
        <DeviceControlSession key={`${props.id}:${auth.token}`} {...props} />
    );
}
function DeviceControlSession({ id, online }: { id: string; online: boolean }) {
    const auth = useAuth();
    const client = useQueryClient();
    const [confirm, setConfirm] = useState<{
        action: string;
        package?: string;
    } | null>(null);
    const [apkError, setApkError] = useState("");
    const [preview, setPreview] = useState<{ url: string; id: string } | null>(
        null,
    );
    const [imageError, setImageError] = useState("");
    const previewOpener = useRef<HTMLElement | null>(null);
    const operations = useOperations(
        new URLSearchParams({ device_id: id, limit: "30" }),
        auth.can("operations.read"),
    );
    const mutation = useMutation({
        mutationFn: (body: {
            action: string;
            package?: string;
            confirmed?: boolean;
        }) =>
            request<Operation>(
                `/api/v1/devices/${encodeURIComponent(id)}/operations`,
                { method: "POST", body: JSON.stringify(body) },
            ),
        onSuccess: () => client.invalidateQueries({ queryKey: ["operations"] }),
    });
    const upload = useMutation({
        mutationFn: (file: File) =>
            request<Operation>(
                `/api/v1/devices/${encodeURIComponent(id)}/apk`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/vnd.android.package-archive",
                    },
                    body: file,
                },
            ),
        onSuccess: () => client.invalidateQueries({ queryKey: ["operations"] }),
    });
    const busy =
        mutation.isPending ||
        upload.isPending ||
        Boolean(operations.data?.items.some(active));
    const allowed = useCallback(
        (action: string) => auth.can(operationPermission(action)),
        [auth],
    );
    const list = operations.data?.items.find(
        (op) => op.action === "apps.list" && op.state === "succeeded",
    );
    const { mutate } = mutation;
    const submit = useCallback(
        (body: { action: string; package?: string; confirmed?: boolean }) =>
            mutate(body),
        [mutate],
    );
    useEffect(
        () => () => {
            if (preview) URL.revokeObjectURL(preview.url);
        },
        [preview],
    );
    async function showImage(op: Operation) {
        previewOpener.current =
            document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null;
        setImageError("");
        try {
            const blob = await protectedImage(
                `/api/v1/operations/${encodeURIComponent(op.id)}/screenshot`,
            );
            setPreview({ url: URL.createObjectURL(blob), id: op.id });
        } catch (error) {
            setImageError(
                error instanceof Error
                    ? error.message
                    : "Screenshot unavailable",
            );
        }
    }
    function actionButton(action: string, label: string, sensitive = false) {
        return (
            <Button
                variant={sensitive ? "destructive" : "outline"}
                type="button"
                aria-busy={
                    mutation.isPending && mutation.variables?.action === action
                }
                key={action}
                disabled={!online || busy || !allowed(action)}
                onClick={() =>
                    sensitive
                        ? setConfirm({ action })
                        : mutation.mutate({ action })
                }
            >
                {label}
            </Button>
        );
    }
    return (
        <section className="panel device-control">
            <h2>Device controls</h2>
            <p className="muted">
                Actions run asynchronously. Results are confirmed by the
                manager. Android may restrict supported actions. Sleep / lock
                follows Android lock timeout and keyguard policy; secure locking
                is not guaranteed.
            </p>
            {!auth.identity && (
                <p role="status">
                    Authorize with a viewer, operator or administrator
                    credential to access device controls.
                </p>
            )}
            {!online && (
                <p className="error">
                    Device offline. Controls are unavailable.
                </p>
            )}
            <div className="device-control-groups">
                <FieldSet className="device-action-group">
                    <FieldLegend>Inspect device</FieldLegend>
                    <div className="actions device-actions">
                        {[
                            ["state", "Inspect state"],
                            ["properties", "Device properties"],
                            ["screenshot", "Capture screenshot"],
                        ].map(([action, label]) => actionButton(action, label))}
                    </div>
                </FieldSet>
                <FieldSet className="device-action-group">
                    <FieldLegend>Screen power</FieldLegend>
                    <div className="actions device-actions">
                        {[
                            ["screen.wake", "Wake screen"],
                            ["screen.lock", "Sleep / lock screen"],
                        ].map(([action, label]) => actionButton(action, label))}
                    </div>
                </FieldSet>
            </div>
            <Separator />
            <FieldSet className="device-action-group device-danger-zone">
                <FieldLegend>Restart device</FieldLegend>
                <p className="muted">
                    These actions interrupt device connectivity and require
                    confirmation.
                </p>
                <div className="actions device-actions">
                    {[
                        ["reboot", "Reboot"],
                        ["reboot.recovery", "Reboot to recovery"],
                        ["reboot.bootloader", "Reboot to bootloader"],
                    ].map(([action, label]) =>
                        actionButton(action, label, true),
                    )}
                </div>
            </FieldSet>
            {mutation.isPending && (
                <p role="status">Requesting device action…</p>
            )}
            {mutation.error && (
                <p className="error" role="alert">
                    {mutation.error?.message}
                </p>
            )}
            <ApplicationsPanel
                list={list}
                operations={operations.data?.items ?? []}
                online={online}
                busy={busy}
                allowed={allowed}
                submit={submit}
                requestConfirm={setConfirm}
                refreshButton={actionButton(
                    "apps.list",
                    "Refresh applications",
                )}
            />
            <div className="device-upload">
                <Field data-invalid={Boolean(apkError || upload.error)}>
                    <FieldLabel>
                        Install APK (default maximum 64 MiB; server
                        configuration may differ)
                        <Input
                            type="file"
                            aria-invalid={Boolean(apkError || upload.error)}
                            aria-describedby={
                                apkError || upload.error
                                    ? `apk-error-${id}`
                                    : undefined
                            }
                            accept=".apk,application/vnd.android.package-archive"
                            disabled={
                                !online || busy || !allowed("apps.install")
                            }
                            onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) {
                                    if (
                                        file.size > 64 * 1024 * 1024 ||
                                        !file.name
                                            .toLowerCase()
                                            .endsWith(".apk")
                                    ) {
                                        setApkError(
                                            "Choose an APK file no larger than the default 64 MiB upload limit. The server may enforce a smaller configured limit.",
                                        );
                                    } else {
                                        setApkError("");
                                        upload.mutate(file);
                                    }
                                }
                                e.target.value = "";
                            }}
                        />
                    </FieldLabel>
                    {(apkError || upload.error) && (
                        <FieldError id={`apk-error-${id}`}>
                            {apkError || upload.error?.message}
                        </FieldError>
                    )}
                </Field>
                {upload.isPending && (
                    <p role="status">
                        Uploading APK for validation and queued installation…
                    </p>
                )}
            </div>
            <div className="device-list-heading">
                <h3>Recent device operations</h3>
                <span className="muted">
                    {operations.data?.items.length ?? 0} loaded
                </span>
            </div>
            {operations.error && (
                <p role="alert" className="error">
                    {operations.error.message}
                </p>
            )}
            <div className="device-operation-columns" aria-hidden="true">
                <span>Operation</span>
                <span>Status</span>
                <span>Duration</span>
                <span>Actions</span>
            </div>
            <ListRegion label="Recent device operations">
                <ul className="device-operation-list">
                    {operations.data?.items.map((op) => (
                        <li key={op.id} className="control-operation">
                            <div className="device-operation-row">
                                <strong>{op.action}</strong>
                                <StateBadge state={op.state} />
                                <span
                                    className={`device-operation-duration ${op.duration == null ? "muted" : ""}`}
                                >
                                    <span className="sr-only">Duration: </span>
                                    {op.duration == null
                                        ? "Unavailable"
                                        : `${op.duration.toFixed(2)} s`}
                                </span>
                                <div className="device-operation-actions">
                                    {op.action === "screenshot" &&
                                        op.state === "succeeded" && (
                                            <Button
                                                variant="outline"
                                                disabled={
                                                    !allowed("screenshot")
                                                }
                                                onClick={() =>
                                                    void showImage(op)
                                                }
                                            >
                                                Preview screenshot
                                            </Button>
                                        )}
                                </div>
                            </div>
                            {op.error && (
                                <p role="alert" className="error">
                                    {op.error}
                                </p>
                            )}
                            {op.result && op.action !== "apps.list" && (
                                <Disclosure
                                    className="device-operation-result"
                                    title={"View operation result"}
                                >
                                    <pre>
                                        {JSON.stringify(op.result, null, 2)}
                                    </pre>
                                </Disclosure>
                            )}
                        </li>
                    ))}
                </ul>
                {!operations.isPending &&
                    !operations.isError &&
                    !operations.data?.items.length && (
                        <p className="muted list-empty">
                            No recent device operations.
                        </p>
                    )}
                {operations.isPending && auth.can("operations.read") && (
                    <p role="status">Loading recent operations…</p>
                )}
                {!auth.can("operations.read") && (
                    <p className="muted list-empty">
                        Operation history permission is required.
                    </p>
                )}
            </ListRegion>
            {imageError && (
                <p className="error" role="alert">
                    {imageError}
                </p>
            )}
            {preview && (
                <Dialog
                    open
                    onOpenChange={(open) => {
                        if (!open) setPreview(null);
                    }}
                >
                    <DialogContent
                        onCloseAutoFocus={(event) => {
                            event.preventDefault();
                            previewOpener.current?.focus();
                        }}
                    >
                        <DialogTitle>Captured device screen</DialogTitle>
                        <DialogDescription>
                            Screenshot from the completed capture operation.
                        </DialogDescription>
                        <img
                            className="capture-preview"
                            src={preview.url}
                            alt="Captured device screen"
                        />
                        <div className="actions device-actions">
                            <Button asChild>
                                <a
                                    href={preview.url}
                                    download={`screenshot-${preview.id}.png`}
                                >
                                    Download screenshot
                                </a>
                            </Button>
                            <Button
                                variant="outline"
                                onClick={() => setPreview(null)}
                            >
                                Close preview
                            </Button>
                        </div>
                    </DialogContent>
                </Dialog>
            )}
            {confirm && (
                <Confirmation
                    title={`Confirm ${confirm.action}`}
                    onCancel={() => setConfirm(null)}
                >
                    <p>{confirmMessage(confirm)}</p>
                    <div className="actions device-dialog-actions">
                        <Button
                            variant="outline"
                            autoFocus
                            onClick={() => setConfirm(null)}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => {
                                mutation.mutate({
                                    ...confirm,
                                    confirmed: true,
                                });
                                setConfirm(null);
                            }}
                        >
                            Confirm action
                        </Button>
                    </div>
                </Confirmation>
            )}
        </section>
    );
}
function confirmMessage({
    action,
    package: name,
}: {
    action: string;
    package?: string;
}) {
    if (action === "apps.uninstall")
        return `${name} will be removed together with its data. A preinstalled app can be restored later from the Removed list; an app installed by a user has to be installed again.`;
    if (action === "apps.stop")
        return `${name} will be stopped immediately. Unsaved work in the app is lost.`;
    return `This action affects ${name ?? "the device"}. Reboot modes depend on device support and may interrupt connectivity.`;
}
