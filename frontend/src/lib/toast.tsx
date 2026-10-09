import { createContext, useContext, useState, type ReactNode } from "react";
type Tone = "success" | "error" | "info";
const ToastContext = createContext<(message: string, tone?: Tone) => void>(
    () => {},
);
export function ToastProvider({ children }: { children: ReactNode }) {
    const [messages, setMessages] = useState<
        { id: number; text: string; tone: Tone }[]
    >([]);
    function notify(text: string, tone: Tone = "info") {
        const id = Date.now() + Math.random();
        setMessages((old) => [...old.slice(-3), { id, text, tone }]);
        setTimeout(
            () => setMessages((old) => old.filter((m) => m.id !== id)),
            6000,
        );
    }
    return (
        <ToastContext.Provider value={notify}>
            {children}
            <div className="toasts" aria-live="polite">
                {messages.map((m) => (
                    <div className={`toast ${m.tone}`} key={m.id}>
                        {m.text}
                        <button
                            aria-label="Dismiss notification"
                            onClick={() =>
                                setMessages((old) =>
                                    old.filter((x) => x.id !== m.id),
                                )
                            }
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
