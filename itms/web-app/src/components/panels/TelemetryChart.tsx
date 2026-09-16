import { useId } from "react";

/** Observed samples only: never invent a trend while the history fills. */
export function TelemetryChart({
  values,
  label,
  color = "#72e5be",
  height = 120,
  max,
}: {
  values: (number | null)[];
  label: string;
  color?: string;
  height?: number;
  max?: number;
}) {
  const id = useId().replace(/:/g, "");
  const valid = values.filter(
    (v): v is number => v !== null && Number.isFinite(v),
  );
  if (valid.length < 2)
    return (
      <div className="chart-empty" style={{ height }}>
        <span className="telemetry-pulse" /> Collecting observations
      </div>
    );
  const ceiling = max ?? Math.max(1, ...valid) * 1.15;
  const points = values.map((v, i) =>
    v === null || !Number.isFinite(v)
      ? null
      : `${(i / Math.max(1, values.length - 1)) * 600},${height - 12 - (v / ceiling) * (height - 24)}`,
  );
  const segments: string[][] = [[]];
  for (const point of points) {
    if (point === null) segments.push([]);
    else segments[segments.length - 1].push(point);
  }
  return (
    <svg
      viewBox={`0 0 600 ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className="telemetry-chart"
      style={{ height }}
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop stopColor={color} stopOpacity=".22" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((y) => (
        <line
          key={y}
          x1="0"
          x2="600"
          y1={height * y}
          y2={height * y}
          stroke="currentColor"
          strokeOpacity=".08"
          strokeDasharray="3 5"
        />
      ))}
      {segments
        .filter((s) => s.length > 1)
        .map((s, i) => (
          <g key={i}>
            <path
              d={`M${s[0].split(",")[0]},${height} L${s.join(" L")} L${s[s.length - 1].split(",")[0]},${height} Z`}
              fill={`url(#${id})`}
            />
            <polyline
              points={s.join(" ")}
              fill="none"
              stroke={color}
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
              strokeLinejoin="round"
            />
          </g>
        ))}
    </svg>
  );
}
