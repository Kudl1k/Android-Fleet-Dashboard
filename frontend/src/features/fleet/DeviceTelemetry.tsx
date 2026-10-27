import Disclosure from "@/components/Disclosure";
import ListRegion from "../../components/ListRegion";
import StateBadge from "../../components/StateBadge";
import { Activity, Battery, HardDrive, Network } from "lucide-react";
import {
    formatMetric,
    metricValue,
    type CurrentMetrics,
    type Metric,
} from "../../lib/api";

const groups = [
    {
        title: "Performance",
        icon: Activity,
        names: [
            "cpu_usage",
            "cpu_core_usage",
            "cpu_frequency",
            "gpu_usage",
            "gpu_frequency",
            "npu_frequency",
            "uptime",
        ],
    },
    {
        title: "Memory & storage",
        icon: HardDrive,
        names: [
            "memory_used",
            "memory_available",
            "memory_total",
            "storage_used",
            "storage_free",
            "storage_total",
        ],
    },
    {
        title: "Battery & thermal",
        icon: Battery,
        names: [
            "battery_level",
            "battery_charging",
            "battery_status",
            "battery_health",
            "battery_temperature",
            "battery_voltage",
            "thermal_temperature",
            "thermal_status",
        ],
    },
    {
        title: "Network",
        icon: Network,
        names: ["network_receive", "network_transmit"],
    },
];
const labels: Record<string, string> = {
    cpu_usage: "CPU utilization",
    cpu_core_usage: "CPU utilization per core",
    cpu_frequency: "CPU frequency",
    gpu_usage: "GPU utilization",
    gpu_frequency: "GPU frequency",
    npu_frequency: "NPU frequency",
    uptime: "Uptime",
    memory_used: "RAM used",
    memory_available: "RAM available",
    memory_total: "RAM total",
    storage_used: "Storage used",
    storage_free: "Storage free",
    storage_total: "Storage total",
    battery_level: "Battery level",
    battery_charging: "Charging",
    battery_status: "Battery status",
    battery_health: "Battery health",
    battery_temperature: "Battery temperature",
    battery_voltage: "Battery voltage",
    thermal_temperature: "Temperature",
    thermal_status: "Thermal status",
    network_receive: "Received",
    network_transmit: "Transmitted",
};
function displayMetric(metric: Metric) {
    if (metric.name === "battery_charging")
        return metric.value === 1 ? "Charging" : "Not charging";
    if (metric.name === "battery_status")
        return (
            {
                1: "Unknown",
                2: "Charging",
                3: "Discharging",
                4: "Not charging",
                5: "Full",
            }[metric.value] ?? "Unknown"
        );
    if (metric.name === "battery_health")
        return (
            {
                1: "Unknown",
                2: "Good",
                3: "Overheat",
                4: "Dead",
                5: "Over voltage",
                6: "Failure",
                7: "Cold",
            }[metric.value] ?? "Unknown"
        );
    return formatMetric(metric.value, metric.unit);
}

/** Separates interfaces whose counters are all zero (idle modem/VoWiFi links) from active ones. */
export function splitIdleInterfaces(values: Metric[]) {
    const busy = new Set(
        values
            .filter((value) => value.value > 0)
            .map((value) => value.labels.interface),
    );
    return {
        active: values.filter((value) => busy.has(value.labels.interface)),
        idle: values.filter((value) => !busy.has(value.labels.interface)),
    };
}

function loadTone(concern: number, warn = 0.75, critical = 0.9) {
    return concern >= critical ? "critical" : concern >= warn ? "warn" : "ok";
}

export default function DeviceTelemetry({
    current,
}: {
    current: CurrentMetrics | undefined;
}) {
    const values = current?.values ?? [];
    const highlights: { label: string; value: string; detail?: string; ratio?: number; tone?: string }[] = [];
    for (const [name, label] of [
        ["cpu_usage", "CPU utilization"],
        ["memory", "RAM utilization"],
        ["storage", "Storage utilization"],
        ["battery_level", "Battery level"],
        ["uptime", "Uptime"],
        ["battery_temperature", "Battery temperature"],
    ]) {
        if (name === "memory" || name === "storage") {
            const used = metricValue(current, `${name}_used`),
                total = metricValue(current, `${name}_total`);
            if (used !== null && total !== null && total > 0) {
                highlights.push({
                    label,
                    value: formatMetric(used / total, "ratio"),
                    detail: `${formatMetric(used, "bytes")} of ${formatMetric(total, "bytes")}`,
                    ratio: used / total,
                    tone: loadTone(used / total),
                });
            } else {
                const metric = values.find(
                    (value) => value.name === `${name}_used`,
                );
                if (metric)
                    highlights.push({
                        label: labels[metric.name],
                        value: displayMetric(metric),
                    });
            }
        } else {
            const metric = values.find((value) => value.name === name);
            if (metric)
                highlights.push({
                    label,
                    value: displayMetric(metric),
                    ...(metric.unit === "ratio" && {
                        ratio: metric.value,
                        tone: name === "battery_level"
                            ? loadTone(1 - metric.value, 0.7, 0.85)
                            : loadTone(metric.value),
                    }),
                });
        }
    }
    // A sparse but usable collection still gets a visible observation, even when
    // none of the usual overview sources are supported by this device.
    if (!highlights.length && values.length) {
        const metric = values[0];
        highlights.push({
            label: labels[metric.name] ?? metric.name.replaceAll("_", " "),
            value: displayMetric(metric),
            detail:
                [
                    metric.name.startsWith("network_")
                        ? "Cumulative counter"
                        : "",
                    ...Object.entries(metric.labels).map(
                        ([key, value]) => `${key}: ${value}`,
                    ),
                ]
                    .filter(Boolean)
                    .join(" · ") || undefined,
        });
    }
    const missing = groups.flatMap((group) =>
        group.names.filter(
            (name) => !values.some((value) => value.name === name),
        ),
    );
    const other = values.filter(
        (value) => !groups.some((group) => group.names.includes(value.name)),
    );
    return (
        <>
            {highlights.length > 0 && (
                <dl className="device-highlights" aria-label="Key observations">
                    {highlights.slice(0, 4).map((item) => (
                        <div key={item.label} data-tone={item.tone}>
                            <dt>{item.label}</dt>
                            <dd>
                                {item.value}
                                {item.ratio !== undefined && (
                                    <span className="meter-track" aria-hidden="true">
                                        <span
                                            className="meter-fill"
                                            style={{ width: `${Math.min(1, Math.max(0, item.ratio)) * 100}%` }}
                                        />
                                    </span>
                                )}
                                {item.detail && <small>{item.detail}</small>}
                            </dd>
                        </div>
                    ))}
                </dl>
            )}
            {current && values.length > 0 && (
                <>
                    <div className="device-metric-groups">
                        {groups.map(({ title, icon: Icon, names }) => {
                            const all = names.flatMap((name) =>
                                values.filter((value) => value.name === name),
                            );
                            const { active, idle } =
                                title === "Network"
                                    ? splitIdleInterfaces(all)
                                    : { active: all, idle: [] };
                            const observations = active;
                            return (
                                <Disclosure
                                    key={title}
                                    className="device-metric-group"
                                    icon={<Icon size={18} aria-hidden="true" />}
                                    title={title}
                                    description={`${observations.length} observations`}
                                >
                                    {title === "Network" && (
                                        <p className="muted">
                                            Cumulative interface counters since
                                            reset, not transfer rates.
                                        </p>
                                    )}
                                    {idle.length > 0 && (
                                        <Disclosure
                                            title={`Interfaces without traffic (${new Set(idle.map((value) => value.labels.interface)).size})`}
                                        >
                                            <MetricList
                                                values={idle}
                                                label="Interfaces without traffic"
                                            />
                                        </Disclosure>
                                    )}
                                    {observations.length ? (
                                        <MetricList
                                            values={observations}
                                            label={`${title} observations`}
                                        />
                                    ) : idle.length ? null : (
                                        <p className="muted">
                                            No observations in this collection.
                                            See metric availability below.
                                        </p>
                                    )}
                                </Disclosure>
                            );
                        })}
                    </div>
                    {other.length > 0 && (
                        <Disclosure
                            className="device-diagnostics"
                            title={`Additional observations (${other.length})`}
                        >
                            <MetricList
                                values={other}
                                label="Additional observations"
                            />
                        </Disclosure>
                    )}
                    <Disclosure
                        className="device-diagnostics"
                        title={`Metric availability · ${missing.length} not observed`}
                    >
                        <p className="muted">
                            Missing from the latest collection. Availability
                            depends on device capabilities, Android permissions,
                            and accessible sources; missing observations do not
                            indicate zero.
                        </p>
                        {missing.length ? (
                            <ListRegion label="Metrics not observed">
                                <ul className="device-unavailable">
                                    {missing.map((name) => (
                                        <li key={name}>{labels[name]}</li>
                                    ))}
                                </ul>
                            </ListRegion>
                        ) : (
                            <p>All listed metrics have observations.</p>
                        )}
                    </Disclosure>
                </>
            )}
        </>
    );
}
function MetricList({ values, label }: { values: Metric[]; label: string }) {
    return (
        <ListRegion label={label}>
            <dl className="metric-list device-observations">
                {values.map((metric, index) => {
                    const text = [
                        "battery_charging",
                        "battery_status",
                        "battery_health",
                    ].includes(metric.name);
                    const formatted = displayMetric(metric);
                    // Split only a single numeric reading and its unit. Composite durations
                    // retain the formatter's complete representation and meaning.
                    const reading = !text
                        ? /^(-?\d+(?:\.\d+)?)(%| [^ ]+)$/.exec(formatted)
                        : null;
                    return (
                        <div
                            key={`${metric.name}-${JSON.stringify(metric.labels)}-${index}`}
                        >
                            <dt>
                                {labels[metric.name] ??
                                    metric.name.replaceAll("_", " ")}
                                {Object.keys(metric.labels).length > 0 && (
                                    <small>
                                        {Object.entries(metric.labels)
                                            .map(
                                                ([key, value]) =>
                                                    `${key}: ${value}`,
                                            )
                                            .join(" · ")}
                                    </small>
                                )}
                            </dt>
                            <dd
                                className={
                                    text ? "metric-text" : "metric-number"
                                }
                            >
                                {text ? (
                                    <StateBadge state={formatted} />
                                ) : reading ? (
                                    <span className="metric-reading">
                                        <span>{reading[1]}</span>
                                        <span className="metric-unit">
                                            {reading[2]}
                                        </span>
                                    </span>
                                ) : (
                                    formatted
                                )}
                            </dd>
                        </div>
                    );
                })}
            </dl>
        </ListRegion>
    );
}
