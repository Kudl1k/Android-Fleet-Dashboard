import {
    createContext,
    useContext,
    useId,
    useLayoutEffect,
    useRef,
    useState,
    type ReactNode,
} from "react";

import { ScrollArea } from "./ui/scroll-area";
import { cn } from "@/lib/utils";

const InListRegion = createContext(false);

/** A naturally sized keyboard scroll target; headings and filters stay outside. */
export default function ListRegion({
    label,
    children,
    className = "",
}: {
    label: string;
    children: ReactNode;
    className?: string;
}) {
    const nested = useContext(InListRegion);
    const region = useRef<HTMLDivElement>(null);
    const hint = useId();
    const [overflowing, setOverflowing] = useState(false);
    useLayoutEffect(() => {
        const element = region.current;
        if (!element) return;
        const measure = () =>
            setOverflowing(element.scrollHeight > element.clientHeight + 1);
        measure();
        if (typeof ResizeObserver === "undefined") return;
        const observer = new ResizeObserver(measure);
        observer.observe(element);
        for (const child of element.children) observer.observe(child);
        return () => observer.disconnect();
    }, [children]);
    if (nested) return <div className={className}>{children}</div>;
    return (
        <div className="list-region-frame">
            <ScrollArea
                type="always"
                className={cn("list-scroll-area", className)}
                viewportRef={region}
                viewportProps={{
                    className: "list-region",
                    role: "region",
                    "aria-label": label,
                    "aria-describedby": overflowing ? hint : undefined,
                    tabIndex: 0,
                }}
            >
                <InListRegion.Provider value={true}>
                    {children}
                </InListRegion.Provider>
            </ScrollArea>
            {overflowing && (
                <p id={hint} className="list-continuation">
                    Scroll for more items
                </p>
            )}
        </div>
    );
}
