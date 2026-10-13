import { ChevronDown } from "lucide-react";
import {
  ANOMALY_SEVERITY_COLOR,
  CORRIDOR_ACCENT_COLOR,
  EV_ROUTE_ALT_COLOR,
  EV_ROUTE_COLOR,
  SIGNAL_COLOR,
  VEHICLE_COLOR,
} from "@/components/map/mapColors";
import { cn } from "@/utils/cn";
import { useMapChromeStore } from "@/store/mapChromeStore";

const ROWS: Array<{ label: string; swatch: React.ReactNode }> = [
  { label: "Car", swatch: <Dot color={VEHICLE_COLOR.car} /> },
  { label: "Motorcycle", swatch: <Dot color={VEHICLE_COLOR.motorcycle} /> },
  { label: "Bus", swatch: <Dot color={VEHICLE_COLOR.bus} /> },
  { label: "Truck", swatch: <Dot color={VEHICLE_COLOR.truck} /> },
  { label: "Emergency vehicle", swatch: <Dot color={VEHICLE_COLOR.ambulance} /> },
  { label: "Emergency route (optimal)", swatch: <Line color={EV_ROUTE_COLOR} /> },
  { label: "Alternative route", swatch: <Line color={EV_ROUTE_ALT_COLOR} /> },
  { label: "Green corridor / preemption", swatch: <Ring color={CORRIDOR_ACCENT_COLOR} /> },
  { label: "Signal — under control", swatch: <Dot color={SIGNAL_COLOR.green} /> },
  { label: "Signal — idle / no data", swatch: <Dot color={SIGNAL_COLOR.red} /> },
  { label: "Signal fault", swatch: <Ring color="#ffa726" /> },
  { label: "Anomaly", swatch: <Dot color={ANOMALY_SEVERITY_COLOR.high} /> },
  { label: "Blocked road", swatch: <Dot color={ANOMALY_SEVERITY_COLOR.blocked} /> },
  {
    label: "Free flow → jam",
    swatch: (
      <span className="h-2 w-10 rounded-full bg-gradient-to-r from-[#63d668] via-[#ff974d] via-60% to-[#811f1f]" />
    ),
  },
];

/**
 * Hidden while an anomaly / emergency card is open (`hidden`) or while the
 * search results or layers menu are showing: those own the space the legend
 * would sit in, and Google Maps likewise tucks secondary chrome away under an
 * open sheet. When open, the legend is capped below the search row and scrolls.
 */
export function MapLegend({ hidden = false }: { hidden?: boolean }) {
  const sheet = useMapChromeStore((s) => s.sheet);
  const toggle = useMapChromeStore((s) => s.toggle);
  const open = sheet === "legend";
  if (hidden || (sheet !== null && !open)) return null;
  return (
    <div className="pointer-events-auto absolute bottom-10 left-3 z-[2] flex max-h-[calc(100%-10rem)] w-52 max-w-[calc(100%-4.75rem)] flex-col overflow-hidden rounded-xl bg-surface-raised shadow-elevation-1">
      <button
        type="button"
        aria-expanded={open}
        aria-label="Map legend"
        onClick={() => toggle("legend")}
        className="flex h-10 w-full shrink-0 items-center justify-between px-3.5 text-left transition-colors hover:bg-muted"
      >
        <span className="text-sm font-medium text-foreground">
          Legend
        </span>
        <ChevronDown
          className={cn(
            "size-4 text-muted-foreground transition-transform duration-200 ease-out",
            !open && "-rotate-90",
          )}
        />
      </button>
      {open && (
        <div className="min-h-0 animate-fade-in space-y-2 overflow-y-auto px-3.5 pb-3.5 pt-1">
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

function Line({ color }: { color: string }) {
  return (
    <span
      className="h-1 w-4 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
    />
  );
}
