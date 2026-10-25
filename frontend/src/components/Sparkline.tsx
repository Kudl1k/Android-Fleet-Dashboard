/** Tiny trend line for 0–1 ratios; decorative, the exact value is shown beside it. */
export default function Sparkline({ values, width = 72, height = 18 }: { values: number[]; width?: number; height?: number }) {
    if (values.length < 2) return null;
    const step = width / (values.length - 1);
    const y = (value: number) => height - 1 - Math.min(1, Math.max(0, value)) * (height - 2);
    const line = values.map((value, index) => `${(index * step).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
    return (
        <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
            <polygon points={`0,${height} ${line} ${width},${height}`} />
            <polyline points={line} />
        </svg>
    );
}
