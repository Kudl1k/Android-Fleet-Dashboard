import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { RotateCcw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "../../lib/auth";
import { useDevices } from "../../lib/hooks";
import { useToast } from "../../lib/toast";
import {
    formatSeconds,
    useRuntimeSettings,
    useSaveSettings,
    type RuntimeSetting,
} from "../../lib/settings";

function SettingRow({ setting, editable }: { setting: RuntimeSetting; editable: boolean }) {
    const save = useSaveSettings();
    const toast = useToast();
    const [draft, setDraft] = useState(String(setting.value));
    const value = Number(draft);
    const valid = draft.trim() !== "" && value >= setting.minimum && value <= setting.maximum;
    const changed = valid && value !== setting.value;
    function submit(event: FormEvent) {
        event.preventDefault();
        if (!changed) return;
        save.mutate(
            { [setting.key]: value },
            {
                onSuccess: () => toast(`${setting.label}: ${formatSeconds(value)}`, "success", { title: "Setting saved" }),
                onError: (error) => toast(error.message, "error", { title: "Setting not saved" }),
            },
        );
    }
    return (
        <form className="setting-row" onSubmit={submit}>
            <div className="setting-text">
                <label htmlFor={`setting-${setting.key}`}>{setting.label}</label>
                <p className="muted">{setting.description}</p>
                <p className="setting-meta">
                    {setting.overridden
                        ? `Changed here · environment default ${formatSeconds(setting.default)}`
                        : "Environment default"}
                    {setting.per_device && " · devices can override it"}
                </p>
            </div>
            <div className="setting-control">
                <span className="setting-input">
                    <input
                        id={`setting-${setting.key}`}
                        type="number"
                        inputMode="numeric"
                        min={setting.minimum}
                        max={setting.maximum}
                        step={1}
                        value={draft}
                        disabled={!editable || save.isPending}
                        aria-invalid={!valid || undefined}
                        aria-describedby={`setting-${setting.key}-range`}
                        onChange={(event) => setDraft(event.target.value)}
                    />
                    <span aria-hidden="true">s</span>
                </span>
                <small id={`setting-${setting.key}-range`} className={valid ? "muted" : "error"}>
                    {setting.minimum}–{setting.maximum} seconds
                </small>
                {editable && (
                    <div className="setting-actions">
                        {(changed || save.isPending) && (
                            <Button type="submit" disabled={save.isPending} aria-busy={save.isPending}>
                                <Save data-icon="inline-start" aria-hidden="true" />
                                {save.isPending ? "Saving…" : "Save"}
                            </Button>
                        )}
                        {setting.overridden && (
                            <Button
                                type="button"
                                variant="outline"
                                disabled={save.isPending}
                                onClick={() =>
                                    save.mutate({ [setting.key]: null }, {
                                        onSuccess: () => setDraft(String(setting.default)),
                                    })
                                }
                            >
                                <RotateCcw data-icon="inline-start" aria-hidden="true" />
                                Reset
                            </Button>
                        )}
                    </div>
                )}
            </div>
        </form>
    );
}

export default function SettingsPage() {
    const auth = useAuth();
    const settings = useRuntimeSettings();
    const devices = useDevices();
    const editable = auth.can("device.manage");
    const overrides = Object.entries(settings.data?.devices ?? {});
    return (
        <>
            <div className="page-heading">
                <div>
                    <h1>Settings</h1>
                    <p className="muted">
                        Collection and evaluation cadence. Changes apply within a second, survive restarts
                        and are written to the audit log. Tokens, keys and ports stay in the server
                        environment.
                    </p>
                </div>
            </div>
            {!auth.can("device.read") ? (
                <p className="panel">Sign in to view settings.</p>
            ) : settings.isPending ? (
                <div className="panel skeleton" role="status" aria-label="Loading settings" />
            ) : settings.isError ? (
                <p className="panel error" role="alert">{settings.error.message}</p>
            ) : (
                <>
                    {!editable && (
                        <p className="muted">Only device managers can change these values.</p>
                    )}
                    <section className="panel settings-list" aria-label="Fleet settings">
                        {settings.data.settings.map((setting) => (
                            <SettingRow
                                key={`${setting.key}-${setting.value}`}
                                setting={setting}
                                editable={editable}
                            />
                        ))}
                    </section>
                    <section className="panel" aria-labelledby="device-overrides-title">
                        <h2 id="device-overrides-title">Per-device collection</h2>
                        {overrides.length ? (
                            <ul className="override-list">
                                {overrides.map(([id, values]) => (
                                    <li key={id}>
                                        <Link to={`/devices/${encodeURIComponent(id)}`}>
                                            {devices.data?.find((device) => device.id === id)?.name ?? id}
                                        </Link>
                                        <span>
                                            every {formatSeconds(values.metrics_interval_seconds)}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className="muted">
                                Every device uses the fleet interval. Open a device to collect it faster or
                                slower, for example while benchmarking.
                            </p>
                        )}
                    </section>
                </>
            )}
        </>
    );
}
