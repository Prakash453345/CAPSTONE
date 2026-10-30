import { useEffect, useId, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { EASE_OUT } from "@/components/console/motion";

interface Point {
  at: number;
  value: number | null;
}

/**
 * A time-series area chart drawn at its real pixel size (no stretched SVG),
 * with a quiet grid, time labels and a hover read-out. Gaps in the data stay
 * gaps: nothing is interpolated across a missing reading.
 */
export function AreaChart({
  points,
  color,
  height = 200,
  max,
  minTop = 0,
  maxTop = Infinity,
  format = (v) => v.toFixed(0),
  label,
}: {
  points: Point[];
  color: string;
  height?: number;
  /** A fixed top for the value axis. */
  max?: number;
  /** Without `max`, the axis fits the data but never shows less than
   *  0-minTop (so 1% congestion isn't drawn as a full-height line) or more
   *  than 0-maxTop. */
  minTop?: number;
  maxTop?: number;
  format?: (v: number) => string;
  label: string;
}) {
  const id = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => e && setWidth(Math.max(200, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const valid = points.filter((p): p is { at: number; value: number } => p.value !== null && Number.isFinite(p.value));
  // the left gutter fits the widest axis label, so "40 km/h" is never clipped
  const peak = valid.length ? Math.max(...valid.map((p) => p.value)) : 1;
  const top = max ?? Math.min(maxTop, niceCeil(Math.max(minTop, peak * 1.1) || 1));
  const labelChars = Math.max(...[0, top / 2, top].map((v) => format(v).length));
  const pad = { l: Math.max(28, labelChars * 6.6 + 12), r: 8, t: 10, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const geom = useMemo(() => {
    if (valid.length < 2) return null;
    const t0 = valid[0]!.at;
    const t1 = valid[valid.length - 1]!.at;
    const hi = top;
    const x = (t: number) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * w;
    const y = (v: number) => pad.t + h - (v / hi) * h;
    const segs: { x: number; y: number; at: number; value: number }[][] = [[]];
    for (const p of points) {
      if (p.value === null || !Number.isFinite(p.value)) {
        if (segs[segs.length - 1]!.length) segs.push([]);
        continue;
      }
      segs[segs.length - 1]!.push({ x: x(p.at), y: y(p.value), at: p.at, value: p.value });
    }
    const flat = segs.flat();
    return { t0, t1, hi, x, y, segs: segs.filter((s) => s.length > 1), flat };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, width, height, top]);

  if (!geom)
    return (
      <div ref={wrap} className="grid place-items-center rounded-xl bg-muted/50 text-[13px] text-muted-foreground" style={{ height }}>
        Collecting observations
      </div>
    );

  const ticks = [0, 0.5, 1].map((f) => geom.hi * f);
  // Under five minutes of history both ends share a minute, so show seconds.
  const short = geom.t1 - geom.t0 < 5 * 60_000;
  const time = (t: number) =>
    new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", ...(short ? { second: "2-digit" } : {}) });
  const hovered = hover !== null ? geom.flat[hover] : null;

  const onMove = (e: React.PointerEvent) => {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const px = e.clientX - r.left;
    let best = 0;
    let bd = Infinity;
    geom.flat.forEach((p, i) => {
      const d = Math.abs(p.x - px);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    setHover(best);
  };

  return (
    <div ref={wrap} className="relative">
      <svg width={width} height={height} role="img" aria-label={label} onPointerMove={onMove} onPointerLeave={() => setHover(null)} className="block touch-none">
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop stopColor={color} stopOpacity="0.22" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={geom.y(v)} y2={geom.y(v)} stroke="hsl(var(--border))" strokeDasharray={v === 0 ? undefined : "3 4"} />
            <text x={pad.l - 8} y={geom.y(v)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px]">
              {format(v)}
            </text>
          </g>
        ))}
        <text x={pad.l} y={height - 6} className="fill-muted-foreground text-[11px]">
          {time(geom.t0)}
        </text>
        <text x={width - pad.r} y={height - 6} textAnchor="end" className="fill-muted-foreground text-[11px]">
          {time(geom.t1)}
        </text>
        {geom.segs.map((s, i) => {
          const line = s.map((p, k) => `${k ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
          const area = `${line} L${s[s.length - 1]!.x.toFixed(1)},${pad.t + h} L${s[0]!.x.toFixed(1)},${pad.t + h} Z`;
          return (
            <g key={i}>
              <path d={area} fill={`url(#g${id})`} />
              <motion.path
                d={line}
                fill="none"
                stroke={color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.9, ease: EASE_OUT }}
              />
            </g>
          );
        })}
        {hovered && (
          <g>
            <line x1={hovered.x} x2={hovered.x} y1={pad.t} y2={pad.t + h} stroke="hsl(var(--muted-foreground))" strokeOpacity="0.35" />
            <circle cx={hovered.x} cy={hovered.y} r={4.5} fill={color} stroke="hsl(var(--surface))" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hovered && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-lg bg-foreground px-2.5 py-1.5 text-[12px] text-background shadow-elevation-2"
          style={{ left: Math.min(width - 60, Math.max(60, hovered.x)), top: Math.max(0, hovered.y - 44) }}
        >
          <span className="font-semibold tabular">{format(hovered.value)}</span>
          <span className="ml-1.5 opacity-70">{new Date(hovered.at).toLocaleTimeString()}</span>
        </div>
      )}
    </div>
  );
}

function niceCeil(v: number) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * p;
}
