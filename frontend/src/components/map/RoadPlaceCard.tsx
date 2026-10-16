import { useEffect } from "react";
import { AlertTriangle, Ambulance, Gauge, Layers, Ruler, Video, X } from "lucide-react";
import { edgeById } from "@/data/network";
import { useMapChromeStore } from "@/store/mapChromeStore";
import { useTrafficStore } from "@/store/trafficStore";
import { PRESET_UNITS, useEmergencyStore } from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import type { AnomalyTarget } from "@/components/map/CreateAnomalyPanel";
import { cn } from "@/utils/cn";
import { cityById } from "@/data/city";

/** Google Maps' traffic wording, on the same thresholds as the road list. */
function trafficLevel(value: number | undefined) {
  if (value == null) return { label: "No live data", tone: "text-muted-foreground", dot: "bg-muted-foreground" };
  if (value > 0.6) return { label: "Heavy traffic", tone: "text-status-critical", dot: "bg-[#f23c32]" };
  if (value > 0.35) return { label: "Slow traffic", tone: "text-status-warn", dot: "bg-[#ff974d]" };
  return { label: "Traffic is flowing", tone: "text-status-ok", dot: "bg-[#63d668]" };
}

/**
 * The place card for a road picked on the map or in search: live condition,
 * road facts and the operator actions that start from a road -- report an
 * anomaly, send a unit, or upload a video of the road for automatic checks. Rendered
 * in the map's left column, so it follows the one-panel-at-a-time rule.
 */
export function RoadPlaceCard({
  onCreateAnomaly,
  onUploadClip,
}: {
  onCreateAnomaly: (target: AnomalyTarget) => void;
  onUploadClip: (target: AnomalyTarget) => void;
}) {
  const selected = useMapChromeStore((s) => s.selectedRoad);
  const selectRoad = useMapChromeStore((s) => s.selectRoad);
  const value = useTrafficStore((s) => (selected ? s.roadCongestion[selected.edgeId] : undefined));
  const startDraft = useEmergencyStore((s) => s.startDraft);
  const setDraftPoint = useEmergencyStore((s) => s.setDraftPoint);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);

  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectRoad(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, selectRoad]);

  const edge = selected ? edgeById.get(selected.edgeId) : undefined;
  if (!selected || !edge) return null;

  const name = edge.name || `Road ${edge.id}`;
  const level = trafficLevel(value);
  const target: AnomalyTarget = { edgeId: edge.id, edgeName: edge.name, at: selected.at };

  const facts = [
    { icon: Layers, label: `${edge.numLanes} ${edge.numLanes === 1 ? "lane" : "lanes"}` },
    { icon: Ruler, label: `${(edge.lengthM / 1000).toFixed(2)} km` },
    { icon: Gauge, label: `${Math.round(edge.speedLimitMps * 3.6)} km/h limit` },
  ];

  return (
    <section
      aria-label={`${name} details`}
      className="pointer-events-auto w-[320px] max-w-full origin-top-left animate-sheet-in overflow-hidden rounded-xl bg-surface-raised shadow-elevation-3"
    >
      <div className="flex items-start gap-3 px-4 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[17px] font-medium leading-6 text-foreground">{name}</h2>
          <p className="text-xs text-muted-foreground">Road · {cityById.get(edge.city)?.name}</p>
        </div>
        <button
          type="button"
          aria-label="Close road details"
          onClick={() => selectRoad(null)}
          className="-mr-1.5 -mt-1 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-4"
        >
          <X />
        </button>
      </div>

      <div className="flex items-center gap-2 px-4 pb-3" aria-live="polite">
        <span className={cn("size-2.5 shrink-0 rounded-full", level.dot)} aria-hidden />
        <span className={cn("text-sm font-medium", level.tone)}>{level.label}</span>
        {value != null && (
          <span className="ml-auto text-sm tabular-nums text-muted-foreground">
            {Math.round(value * 100)}% occupied
          </span>
        )}
      </div>

      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border px-4 py-3 text-xs text-muted-foreground">
        {facts.map(({ icon: Icon, label }) => (
          <li key={label} className="flex items-center gap-1.5">
            <Icon className="size-3.5" aria-hidden />
            {label}
          </li>
        ))}
      </ul>

      <div className="flex gap-2 border-t border-border px-4 py-3">
        <button
          type="button"
          onClick={() => {
            selectRoad(null);
            setInteractionMode("create-anomaly");
            onCreateAnomaly(target);
          }}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-primary-muted px-2.5 text-[13px] font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground [&_svg]:size-4"
        >
          <AlertTriangle />
          Create anomaly
        </button>
        <button
          type="button"
          onClick={() => {
            selectRoad(null);
            startDraft(PRESET_UNITS[0]);
            setDraftPoint("destination", target);
          }}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-input px-2.5 text-[13px] font-medium text-primary transition-colors hover:bg-primary-muted [&_svg]:size-4"
        >
          <Ambulance />
          Send unit here
        </button>
      </div>
      <div className="border-t border-border px-4 py-3">
        <button
          type="button"
          onClick={() => {
            selectRoad(null);
            onUploadClip(target);
          }}
          className="flex h-9 w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-input px-2.5 text-[13px] font-medium text-primary transition-colors hover:bg-primary-muted [&_svg]:size-4"
        >
          <Video />
          Check a video of this road
        </button>
      </div>
    </section>
  );
}
