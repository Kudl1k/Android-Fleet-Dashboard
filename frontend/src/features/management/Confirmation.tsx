import { useEffect, useRef, type ReactNode } from "react";
export default function Confirmation({
    title,
    children,
    onCancel,
}: {
    title: string;
    children: ReactNode;
    onCancel: () => void;
}) {
    const dialog = useRef<HTMLDialogElement>(null);
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        dialog.current?.showModal();
        return () => {
            previous?.focus();
        };
    }, []);
    return (
        <dialog
            ref={dialog}
            className="panel"
            aria-label={title}
            onCancel={onCancel}
        >
            <h2>{title}</h2>
            {children}
        </dialog>
    );
}
