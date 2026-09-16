import { useState } from "react";
import { ChevronDown } from "lucide-react";
import {
  ANOMALY_SEVERITY_COLOR,
  SIGNAL_COLOR,
  VEHICLE_COLOR,
} from "@/components/map/mapColors";
import { cn } from "@/utils/cn";

const ROWS: Array<{ label: string; swatch: React.ReactNode }> = [
  { label: "Car", swatch: <Dot color={VEHICLE_COLOR.car} /> },
  { label: "Bus", swatch: <Dot color={VEHICLE_COLOR.bus} /> },
  { label: "Truck", swatch: <Dot color={VEHICLE_COLOR.truck} /> },
  { label: "Emergency", swatch: <Dot color={VEHICLE_COLOR.ambulance} /> },
  { label: "Signal — under control", swatch: <Dot color={SIGNAL_COLOR.green} /> },
  { label: "Signal — idle / no data", swatch: <Dot color={SIGNAL_COLOR.red} /> },
  { label: "Corridor preemption", swatch: <Ring color="#5fd0ff" /> },
  { label: "Signal fault", swatch: <Ring color="#ffa726" /> },
  { label: "Anomaly", swatch: <Dot color={ANOMALY_SEVERITY_COLOR.high} /> },
  { label: "Blocked road", swatch: <Dot color={ANOMALY_SEVERITY_COLOR.blocked} /> },
  {
    label: "Free flow → jam",
    swatch: (
      <span className="h-2 w-10 rounded-full bg-gradient-to-r from-[#3f6b52] via-[#e0a12a] to-[#c0392b]" />
    ),
  },
];

export function MapLegend() {
  const [open, setOpen] = useState(false);
  return (
    <div className="pointer-events-auto absolute bottom-3 left-3 w-44 overflow-hidden rounded-lg border border-border bg-surface/90 backdrop-blur-sm shadow-panel">
      <button
        type="button"
        aria-expanded={open}
        aria-label="Map legend"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
      >
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Legend
        </span>
        <ChevronDown
          className={cn(
            "size-3.5 text-muted-foreground transition-transform",
            !open && "-rotate-90",
          )}
        />
      </button>
      {open && (
        <div className="space-y-1.5 px-3 pb-3">
          {ROWS.map((r) => (
            <div key={r.label} className="flex items-center gap-2 text-xs">
              {r.swatch}
              <span className="text-muted-foreground">{r.label}</span>
            </div>
          ))}
          <p className="border-t border-border pt-1.5 text-[10px] italic leading-snug text-muted-foreground/80">
            Signal colour shows controller activity, not a real per-approach
            phase reading.
          </p>
        </div>
      )}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return (
    <span
      className="size-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
    />
  );
}

function Ring({ color }: { color: string }) {
  return (
    <span
      className="size-2.5 shrink-0 rounded-full border-2"
      style={{ borderColor: color }}
    />
  );
}
