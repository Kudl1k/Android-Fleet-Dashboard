import { useEffect, useState } from "react";

/** Current time that re-renders the caller on a fixed cadence. */
export function useNow(interval = 10000) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), interval);
        return () => window.clearInterval(timer);
    }, [interval]);
    return now;
}

export function relativeTime(iso: string | null, now: number): string {
    if (!iso) return "never";
    const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
    if (Number.isNaN(seconds)) return "unknown";
    if (seconds < 10) return "just now";
    if (seconds < 60) return `${seconds} s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return `${hours} h ago`;
    return `${Math.floor(hours / 24)} d ago`;
}
