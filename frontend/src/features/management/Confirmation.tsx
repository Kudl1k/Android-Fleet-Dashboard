import { useRef, type ReactNode } from "react";
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export default function Confirmation({
    title,
    children,
    onCancel,
}: {
    title: string;
    children: ReactNode;
    onCancel: () => void;
}) {
    const opener = useRef(
        document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null,
    );
    return (
        <AlertDialog
            open
            onOpenChange={(open) => {
                if (!open) onCancel();
            }}
        >
            <AlertDialogContent
                onOpenAutoFocus={(event) => {
                    event.preventDefault();
                    const content = event.currentTarget as HTMLElement;
                    content.querySelector<HTMLButtonElement>("button")?.focus();
                }}
                onCloseAutoFocus={(event) => {
                    event.preventDefault();
                    if (opener.current?.isConnected) opener.current.focus();
                }}
            >
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription>
                        Review the action before confirming.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="confirmation-body">{children}</div>
            </AlertDialogContent>
        </AlertDialog>
    );
}
