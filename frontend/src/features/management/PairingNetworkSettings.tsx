import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../lib/api";
import { useAuth } from "../../lib/auth";

type ApprovedNetwork = { network: string; created_at: number; created_by: string };
type NetworkResponse = { networks: ApprovedNetwork[] };

export default function PairingNetworkSettings() {
    const { can } = useAuth();
    const client = useQueryClient();
    const [network, setNetwork] = useState("");
    const query = useQuery({
        queryKey: ["pairing-allowed-networks"],
        queryFn: () => request<NetworkResponse>("/api/v1/pairing/allowed-networks"),
        enabled: can("security.manage"),
        retry: false,
    });
    const mutation = useMutation({
        mutationFn: ({ value, remove }: { value: string; remove: boolean }) =>
            request<NetworkResponse>("/api/v1/pairing/allowed-networks", {
                method: remove ? "DELETE" : "POST",
                body: JSON.stringify({ network: value }),
            }),
        onSuccess: (result) => {
            setNetwork("");
            client.setQueryData(["pairing-allowed-networks"], result);
        },
        onError: () => void client.invalidateQueries({ queryKey: ["pairing-allowed-networks"] }),
    });
    if (!can("security.manage")) return null;
    function add(event: FormEvent) {
        event.preventDefault();
        mutation.mutate({ value: network, remove: false });
    }
    return (
        <section className="panel pairing-network-settings">
            <h2>Wireless Debugging network access</h2>
            <p className="muted">
                Approve a phone’s private IP or trusted Wi-Fi subnet here. These approvals
                persist with the fleet database, so Docker settings are not needed for each
                network. IPv4 ranges must be /16 or narrower; IPv6 ULA ranges /48 or narrower.
            </p>
            <form onSubmit={add}>
                <label>
                    Private IP or CIDR
                    <input
                        required
                        maxLength={64}
                        value={network}
                        onChange={(event) => setNetwork(event.target.value)}
                        placeholder="10.42.0.0/24"
                        aria-label="Private IP or CIDR"
                    />
                </label>
                <button disabled={mutation.isPending}>
                    {mutation.isPending ? "Saving…" : "Approve network"}
                </button>
            </form>
            {query.isPending && <p role="status">Loading approved networks…</p>}
            {(query.error || mutation.error) && (
                <p role="alert" className="error">
                    {(mutation.error ?? query.error)?.message}
                </p>
            )}
            {query.data?.networks.length === 0 && <p>No pairing networks approved yet.</p>}
            {query.data?.networks.map((item) => (
                <div className="pairing-network-row" key={item.network}>
                    <span>
                        <code>{item.network}</code>
                        <small className="muted">Added by {item.created_by}</small>
                    </span>
                    <button
                        className="button"
                        disabled={mutation.isPending}
                        onClick={() => mutation.mutate({ value: item.network, remove: true })}
                    >
                        Revoke
                    </button>
                </div>
            ))}
        </section>
    );
}
