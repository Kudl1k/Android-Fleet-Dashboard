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
    // Capture before child autofocus and keep the opener through StrictMode replay.
    const opener = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    useEffect(() => {
        const element = dialog.current;
        const previous = opener.current;
        element?.showModal();
        return () => {
            if (element?.open) element.close();
            if (previous?.isConnected) previous.focus();
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
