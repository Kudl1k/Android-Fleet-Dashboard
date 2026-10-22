import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "./ui/collapsible";
import { cn } from "@/lib/utils";

/** forceMount plus hidden preserves drafts and explicit session ownership. */
export default function Disclosure({
    title,
    description,
    icon,
    children,
    className,
    onOpenChange,
}: {
    title: ReactNode;
    description?: ReactNode;
    icon?: ReactNode;
    children: ReactNode;
    className?: string;
    onOpenChange?: (open: boolean) => void;
}) {
    const [open, setOpen] = useState(false);
    return (
        <Collapsible
            open={open}
            onOpenChange={(value) => {
                setOpen(value);
                onOpenChange?.(value);
            }}
            className={cn("device-disclosure", className)}
        >
            <CollapsibleTrigger className="device-disclosure-trigger">
                {icon}
                <span className="disclosure-copy">
                    <strong>{title}</strong>
                    {description && (
                        <>
                            {" "}
                            <span className="muted">{description}</span>
                        </>
                    )}
                </span>
                <ChevronDown
                    aria-hidden="true"
                    className="disclosure-chevron"
                />
            </CollapsibleTrigger>
            <CollapsibleContent
                forceMount
                hidden={!open}
                className="device-disclosure-body"
            >
                {children}
            </CollapsibleContent>
        </Collapsible>
    );
}
