import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";

type ApprovedDestination = { destination: string; created_at: number; created_by: string };
type DestinationResponse = { destinations: ApprovedDestination[] };

export default function SSHDestinationSettings() {
    const { can } = useAuth();
    const client = useQueryClient();
    const [destination, setDestination] = useState("");
    const query = useQuery({
        queryKey: ["ssh-approved-destinations"],
        queryFn: () => request<DestinationResponse>("/api/v1/ssh/destinations"),
        enabled: can("terminal:profile:manage"),
        retry: false,
    });
    const mutation = useMutation({
        mutationFn: ({ value, remove }: { value: string; remove: boolean }) =>
            request<DestinationResponse>("/api/v1/ssh/destinations", {
                method: remove ? "DELETE" : "POST",
                body: JSON.stringify({ destination: value }),
            }),
        onSuccess: (result) => {
            setDestination("");
            client.setQueryData(["ssh-approved-destinations"], result);
        },
        onError: () =>
            void client.invalidateQueries({ queryKey: ["ssh-approved-destinations"] }),
    });
    if (!can("terminal:profile:manage")) return null;
    function add(event: FormEvent) {
        event.preventDefault();
        mutation.mutate({ value: destination, remove: false });
    }
    return (
        <section className="panel pairing-network-settings">
            <h2>SSH destination access</h2>
            <p className="muted">
                Approve the exact host and port an SSH profile may connect to. These approvals
                persist with the SSH database, so Docker settings are not needed for each
                destination. Termux setup approves its phone automatically.
            </p>
            <form onSubmit={add}>
                <label>
                    Host:port
                    <input
                        required
                        maxLength={260}
                        value={destination}
                        onChange={(event) => setDestination(event.target.value)}
                        placeholder="192.168.0.34:8022"
                        aria-label="Host:port"
                    />
                </label>
                <button disabled={mutation.isPending}>
                    {mutation.isPending ? "Saving…" : "Approve destination"}
                </button>
            </form>
            {query.isPending && <p role="status">Loading approved destinations…</p>}
            {(query.error || mutation.error) && (
                <p role="alert" className="error">
                    {(mutation.error ?? query.error)?.message}
                </p>
            )}
            {query.data?.destinations.length === 0 && <p>No SSH destinations approved yet.</p>}
            {query.data?.destinations.map((item) => (
                <div className="pairing-network-row" key={item.destination}>
                    <span>
                        <code>{item.destination}</code>
                        <small className="muted">Added by {item.created_by}</small>
                    </span>
                    <button
                        className="button"
                        disabled={mutation.isPending}
                        onClick={() => mutation.mutate({ value: item.destination, remove: true })}
                    >
                        Revoke
                    </button>
                </div>
            ))}
        </section>
    );
}
