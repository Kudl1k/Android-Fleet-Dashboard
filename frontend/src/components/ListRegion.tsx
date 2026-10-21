import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** A naturally sized keyboard scroll target; headings and filters stay outside. */
export default function ListRegion({ label, children, className = "" }: {
    label: string;
    children: ReactNode;
    className?: string;
}) {
    const region = useRef<HTMLDivElement>(null);
    const hint = useId();
    const [overflowing, setOverflowing] = useState(false);
    useLayoutEffect(() => {
        const element = region.current;
        if (!element) return;
        const measure = () => setOverflowing(element.scrollHeight > element.clientHeight + 1);
        measure();
        if (typeof ResizeObserver === "undefined") return;
        const observer = new ResizeObserver(measure);
        observer.observe(element);
        for (const child of element.children) observer.observe(child);
        return () => observer.disconnect();
    }, [children]);
    return <div className="list-region-frame">
        <div ref={region} className={`list-region ${className}`} role="region" aria-label={label} aria-describedby={overflowing ? hint : undefined} tabIndex={0}>{children}</div>
        {overflowing && <p id={hint} className="list-continuation">Scroll for more items</p>}
    </div>;
}
