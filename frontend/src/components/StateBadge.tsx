export default function StateBadge({ state }: { state: string }) {
    return <span className="badge state-badge" data-state={state}>{state ? state.replaceAll("_", " ") : "Unknown"}</span>;
}
