import { Badge } from "./ui/badge";
export default function StateBadge({ state }: { state: string }) {
    return (
        <Badge variant="outline" className="state-badge" data-state={state}>
            {state ? state.replaceAll("_", " ") : "Unknown"}
        </Badge>
    );
}
