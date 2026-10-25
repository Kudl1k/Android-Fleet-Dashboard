import { useMemo, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { CornerDownLeft, FileText, Search, Smartphone } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useDevices } from "../lib/hooks";
import { fleetGroup } from "../features/fleet/fleetState";

export interface PaletteRoute {
    label: string;
    path: string;
}

/** Ctrl+K jump list for devices and pages; selection only navigates, it never runs actions. */
export default function CommandPalette({
    open,
    onOpenChange,
    routes,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    routes: PaletteRoute[];
}) {
    const devices = useDevices();
    const navigate = useNavigate();
    const [query, setQuery] = useState("");
    const [active, setActive] = useState(0);
    const items = useMemo(() => {
        const needle = query.trim().toLowerCase();
        const all = [
            ...(devices.data ?? []).map((device) => ({
                key: `device:${device.id}`,
                kind: "device" as const,
                label: device.name,
                detail: [device.model, device.host ?? device.serial].filter(Boolean).join(" · "),
                group: fleetGroup(device),
                path: `/devices/${encodeURIComponent(device.id)}`,
            })),
            ...routes.map((route) => ({
                key: `page:${route.path}`,
                kind: "page" as const,
                label: route.label,
                detail: "Page",
                group: "",
                path: route.path,
            })),
        ];
        return needle
            ? all.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(needle))
            : all;
    }, [devices.data, routes, query]);
    const current = Math.min(active, Math.max(0, items.length - 1));
    function close(next: boolean) {
        onOpenChange(next);
        if (!next) {
            setQuery("");
            setActive(0);
        }
    }
    function go(path: string) {
        close(false);
        navigate(path);
    }
    function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!items.length) return;
            const step = event.key === "ArrowDown" ? 1 : -1;
            setActive((current + step + items.length) % items.length);
        } else if (event.key === "Enter" && items[current]) {
            event.preventDefault();
            go(items[current].path);
        }
    }
    return (
        <Dialog open={open} onOpenChange={close}>
            <DialogContent className="command-palette" showCloseButton={false}>
                <DialogTitle className="sr-only">Go to device or page</DialogTitle>
                <DialogDescription className="sr-only">
                    Type to filter, use the arrow keys to choose and Enter to open.
                </DialogDescription>
                <div className="palette-search">
                    <Search size={18} aria-hidden="true" />
                    <input
                        autoFocus
                        role="combobox"
                        aria-expanded="true"
                        aria-controls="palette-results"
                        aria-activedescendant={items[current] ? `palette-${current}` : undefined}
                        aria-label="Search devices and pages"
                        placeholder="Jump to a device or page…"
                        value={query}
                        onChange={(event) => {
                            setQuery(event.target.value);
                            setActive(0);
                        }}
                        onKeyDown={onKeyDown}
                    />
                    <kbd>Esc</kbd>
                </div>
                <ul id="palette-results" role="listbox" aria-label="Results" className="palette-results">
                    {items.map((item, index) => (
                        <li
                            key={item.key}
                            id={`palette-${index}`}
                            role="option"
                            aria-selected={index === current}
                            onMouseMove={() => setActive(index)}
                            onClick={() => go(item.path)}
                        >
                            {item.kind === "device" ? (
                                <Smartphone size={16} aria-hidden="true" />
                            ) : (
                                <FileText size={16} aria-hidden="true" />
                            )}
                            <span className="palette-label">{item.label}</span>
                            <span className="palette-detail">
                                {item.group && <i className={`led ${item.group}`} aria-hidden="true" />}
                                {item.detail}
                            </span>
                            {index === current && <CornerDownLeft size={14} aria-hidden="true" />}
                        </li>
                    ))}
                    {!items.length && <li className="palette-empty">No devices or pages match “{query}”.</li>}
                </ul>
            </DialogContent>
        </Dialog>
    );
}
