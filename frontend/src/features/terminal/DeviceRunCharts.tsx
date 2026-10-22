import {
    NativeSelect,
    NativeSelectOption,
} from "@/components/ui/native-select";
import { Field, FieldLabel } from "@/components/ui/field";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import RunTelemetry, { type DeviceRecording } from "./RunTelemetry";

interface RecordedRun {
    id: string;
    device_id: string;
    command: string;
    created_at: number;
    state: string;
    device_recording?: DeviceRecording;
}
export default function DeviceRunCharts({ deviceId }: { deviceId: string }) {
    const auth = useAuth();
    const [selected, setSelected] = useState("");
    const sessions = useQuery({
        queryKey: ["recorded-device-runs", deviceId],
        queryFn: ({ signal }) =>
            request<{ items: RecordedRun[] }>("/api/v1/terminal/sessions", {
                signal,
            }),
        refetchInterval: 15000,
        enabled: auth.can("terminal:view") && auth.can("terminal:ssh"),
    });
    const runs =
        sessions.data?.items.filter(
            (item) =>
                item.device_id === deviceId && item.device_recording?.enabled,
        ) ?? [];
    const selectedRun = runs.find((item) => item.id === selected);
    if (!auth.can("terminal:ssh")) return null;
    return (
        <section className="panel">
            <h3>Program run charts</h3>
            <Field>
                <FieldLabel>
                    Recorded device run
                    <NativeSelect
                        value={selected}
                        onChange={(event) => setSelected(event.target.value)}
                    >
                        <NativeSelectOption value="">
                            Select a recorded run
                        </NativeSelectOption>
                        {runs.map((run) => (
                            <NativeSelectOption key={run.id} value={run.id}>
                                {new Date(
                                    run.created_at * 1000,
                                ).toLocaleString()}{" "}
                                — {run.command} — {run.state}
                            </NativeSelectOption>
                        ))}
                    </NativeSelect>
                </FieldLabel>
            </Field>
            {sessions.isError && <p role="alert">{sessions.error.message}</p>}
            {!runs.length && (
                <p className="muted">
                    Start a program run with “Record device statistics” enabled
                    to save a run-specific chart.
                </p>
            )}
            {selectedRun?.device_recording && (
                <RunTelemetry
                    key={selectedRun.id}
                    sessionId={selectedRun.id}
                    deviceId={deviceId}
                    active={selectedRun.state === "active"}
                    recording={selectedRun.device_recording}
                />
            )}
        </section>
    );
}
