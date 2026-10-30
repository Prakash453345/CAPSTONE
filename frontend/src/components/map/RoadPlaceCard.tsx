import { useEffect } from "react";
import { AlertTriangle, Ambulance, Gauge, Layers, Ruler, Video, X } from "lucide-react";
import { edgeById, roadLabel } from "@/data/network";
import { useMapChromeStore } from "@/store/mapChromeStore";
import { useTrafficStore } from "@/store/trafficStore";
import { CREW_TYPES, useEmergencyStore } from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import type { AnomalyTarget } from "@/components/map/CreateAnomalyPanel";
import { cn } from "@/utils/cn";
import { LIVE_CITY, cityById } from "@/data/city";

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

  const name = roadLabel(edge);
  const level = trafficLevel(value);
  const target: AnomalyTarget = { edgeId: edge.id, edgeName: edge.name, at: selected.at };
  const live = edge.city === LIVE_CITY;

  const facts = [
    { icon: Layers, label: `${edge.numLanes} ${edge.numLanes === 1 ? "lane" : "lanes"}` },
    { icon: Ruler, label: `${(edge.lengthM / 1000).toFixed(2)} km` },
    { icon: Gauge, label: `${Math.round(edge.speedLimitMps * 3.6)} km/h limit` },
  ];

  return (
    <section
      aria-label={`${name} details`}
      className="pointer-events-auto w-[344px] max-w-full origin-top-left animate-sheet-in overflow-hidden rounded-[20px] bg-surface-raised shadow-elevation-3"
    >
      <div className="flex items-start gap-3 px-4 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[17px] font-semibold leading-6 tracking-[-0.01em] text-foreground">{name}</h2>
          <p className="text-xs text-muted-foreground">Road · {cityById.get(edge.city)?.name}</p>
        </div>
        <button
          type="button"
          aria-label="Close road details"
          onClick={() => selectRoad(null)}
          className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground transition-colors hover:text-foreground [&_svg]:size-4"
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

      <ul className="mx-4 mb-3 flex flex-wrap gap-x-4 gap-y-1.5 rounded-xl bg-surface-fill px-3 py-2.5 text-xs text-muted-foreground">
        {facts.map(({ icon: Icon, label }) => (
          <li key={label} className="flex items-center gap-1.5">
            <Icon className="size-3.5" aria-hidden />
            {label}
          </li>
        ))}
      </ul>

      {live ? (
        <div className="grid grid-cols-3 gap-2 px-4 pb-4 pt-1">
          <ActionButton
            icon={<AlertTriangle />}
            label="Report"
            onClick={() => {
              selectRoad(null);
              setInteractionMode("create-anomaly");
              onCreateAnomaly(target);
            }}
          />
          <ActionButton
            icon={<Ambulance />}
            label="Send help"
            primary
            onClick={() => {
              selectRoad(null);
              startDraft(CREW_TYPES[0]);
              setDraftPoint("destination", target);
            }}
          />
          <ActionButton
            icon={<Video />}
            label="Check video"
            onClick={() => {
              selectRoad(null);
              onUploadClip(target);
            }}
          />
        </div>
      ) : (
        <p className="mx-4 mb-4 rounded-xl bg-surface-fill px-3 py-2 text-[12px] text-muted-foreground">
          {cityById.get(edge.city)?.name} is shown for its roads and signal plans. Incidents and dispatch run on
          the live {cityById.get(LIVE_CITY)?.name} simulation.
        </p>
      )}
    </section>
  );
}

/** Apple Maps' row of round action buttons under a place's name. */
function ActionButton({
  icon,
  label,
  onClick,
  primary,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex h-[58px] flex-col items-center justify-center gap-1 rounded-[14px] text-[12px] font-medium transition-[filter,background-color] duration-150 [&_svg]:size-[18px]",
        primary
          ? "bg-primary text-primary-foreground hover:brightness-105"
          : "bg-surface-fill text-primary hover:bg-muted",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
