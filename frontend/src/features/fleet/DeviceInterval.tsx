import { useAuth } from "../../lib/auth";
import { formatSeconds, useRuntimeSettings, useSaveSettings } from "../../lib/settings";

const presets = [5, 10, 15, 30, 60, 120, 300];

/** Shows how often this device is sampled and lets managers override the fleet cadence. */
export default function DeviceInterval({ deviceId }: { deviceId: string }) {
    const auth = useAuth();
    const settings = useRuntimeSettings();
    const save = useSaveSettings(deviceId);
    const fleet = settings.data?.settings.find((item) => item.key === "metrics_interval_seconds");
    if (!fleet) return null;
    const override = settings.data?.devices[deviceId]?.metrics_interval_seconds;
    const current = override ?? fleet.value;
    if (!auth.can("device.manage"))
        return (
            <p className="muted device-interval">
                Collected every {formatSeconds(current)}
                {override === undefined ? " (fleet default)" : ""}
            </p>
        );
    const options = [...new Set([...presets, current])]
        .filter((value) => value >= fleet.minimum && value <= fleet.maximum)
        .sort((a, b) => a - b);
    return (
        <label className="device-interval">
            Collect every
            <select
                value={override === undefined ? "" : String(override)}
                disabled={save.isPending}
                aria-busy={save.isPending}
                onChange={(event) =>
                    save.mutate({
                        metrics_interval_seconds: event.target.value === "" ? null : Number(event.target.value),
                    })
                }
            >
                <option value="">Fleet default ({formatSeconds(fleet.value)})</option>
                {options.map((value) => (
                    <option key={value} value={value}>
                        {formatSeconds(value)}
                    </option>
                ))}
            </select>
            {save.isError && <span className="error" role="alert">{save.error.message}</span>}
        </label>
    );
}
