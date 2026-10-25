import { PlugZap, Unplug } from "lucide-react";

/** Phone outline whose screen fills with the observed battery level. */
export default function PhoneGlyph({
    group,
    battery,
    charging,
    size = "md",
}: {
    group: string;
    battery: number | null;
    charging: boolean;
    size?: "md" | "lg";
}) {
    const level = battery === null ? null : Math.min(1, Math.max(0, battery));
    const tone =
        level === null ? "none" : level <= 0.15 ? "critical" : level <= 0.3 ? "warn" : "ok";
    return (
        <span className="phone-glyph" data-group={group} data-size={size} aria-hidden="true">
            <span className="phone-screen">
                {level !== null && (
                    <span
                        className="phone-charge"
                        data-tone={tone}
                        style={{ height: `${level * 100}%` }}
                    />
                )}
                <span className="phone-readout">
                    {group !== "online" ? (
                        <Unplug size={size === "lg" ? 22 : 16} />
                    ) : level === null ? (
                        "—"
                    ) : (
                        <>
                            <span>
                                {Math.round(level * 100)}
                                <small>%</small>
                            </span>
                            {charging && <PlugZap className="phone-plug" size={size === "lg" ? 16 : 13} />}
                        </>
                    )}
                </span>
            </span>
        </span>
    );
}
