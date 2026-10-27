import type { Operation } from "./operations";

export type AppCategory = "protected" | "removable" | "system" | "user";
export interface AppEntry {
    package: string;
    system?: boolean;
    category?: AppCategory;
    size_bytes?: number | null;
}
export interface AppList {
    apps: AppEntry[];
    removed: string[];
    /** False for results from older managers that only return package names. */
    classified: boolean;
}
export type AppFilter = "removable" | "user" | "kept" | "removed" | "all";

const CATEGORIES = new Set(["protected", "removable", "system", "user"]);
export const APP_CHANGES = new Set([
    "apps.uninstall",
    "apps.restore",
    "apps.cleanup",
    "apps.install",
]);

export function parseAppList(op: Operation | undefined): AppList {
    const result = op?.result ?? {};
    const removed = Array.isArray(result.removed)
        ? result.removed.filter(
              (item): item is string => typeof item === "string",
          )
        : [];
    if (Array.isArray(result.apps)) {
        const apps = result.apps.flatMap((item) => {
            const entry = item as Partial<AppEntry>;
            if (typeof entry.package !== "string") return [];
            return [
                {
                    package: entry.package,
                    system: entry.system === true,
                    category: CATEGORIES.has(String(entry.category))
                        ? (entry.category as AppCategory)
                        : undefined,
                    size_bytes:
                        typeof entry.size_bytes === "number"
                            ? entry.size_bytes
                            : null,
                },
            ];
        });
        return { apps, removed, classified: true };
    }
    const raw = result.packages ?? result.applications ?? [];
    const apps = Array.isArray(raw)
        ? raw
              .map((item) =>
                  typeof item === "string"
                      ? item
                      : String(
                            (item as { package?: string; name?: string })
                                .package ??
                                (item as { name?: string }).name ??
                                "",
                        ),
              )
              .filter(Boolean)
              .map((name) => ({ package: name }))
        : [];
    return { apps, removed, classified: false };
}

export function matchesFilter(app: AppEntry, filter: AppFilter) {
    if (filter === "all") return true;
    if (filter === "kept")
        return app.category === "protected" || app.category === "system";
    return app.category === filter;
}

export function canRemove(app: AppEntry) {
    return app.category === "removable" || app.category === "user";
}

export function formatSize(bytes: number) {
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1000 && unit < units.length - 1) {
        value /= 1000;
        unit++;
    }
    return `${value >= 100 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}
