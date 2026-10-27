import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
type Tone = "success" | "error" | "info";
interface ToastOptions {
    title?: string;
    /** In-app link shown as "Open"; errors stay longer so they are not missed. */
    href?: string;
}
type Notify = (message: string, tone?: Tone, options?: ToastOptions) => void;
const ToastContext = createContext<Notify>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
    const [messages, setMessages] = useState<
        { id: number; text: string; tone: Tone; title?: string; href?: string }[]
    >([]);
    const dismiss = useCallback(
        (id: number) => setMessages((old) => old.filter((m) => m.id !== id)),
        [],
    );
    const notify = useCallback<Notify>(
        (text, tone = "info", options = {}) => {
            const id = Date.now() + Math.random();
            setMessages((old) => [...old.slice(-3), { id, text, tone, ...options }]);
            setTimeout(() => dismiss(id), tone === "error" ? 15000 : 6000);
        },
        [dismiss],
    );
    return (
        <ToastContext.Provider value={notify}>
            {children}
            <div className="toasts" aria-live="polite">
                {messages.map((m) => (
                    <div className={`toast ${m.tone}`} key={m.id}>
                        <i className="toast-led" aria-hidden="true" />
                        <div className="toast-text">
                            {m.title && <strong>{m.title}</strong>}
                            <span>{m.text}</span>
                        </div>
                        {m.href && (
                            <Link className="toast-link" to={m.href} onClick={() => dismiss(m.id)}>
                                Open
                            </Link>
                        )}
                        <button
                            aria-label="Dismiss notification"
                            onClick={() => dismiss(m.id)}
                        >
                            ×
                        </button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}
export function useToast() {
    return useContext(ToastContext);
}
