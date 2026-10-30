import { useId, useMemo, useRef, useState } from "react";
import { Crosshair, MapPin, Search, X } from "lucide-react";
import { roadEdges, roadLabel } from "@/data/network";
import { LIVE_CITY, cityById } from "@/data/city";
import { cn } from "@/utils/cn";

export interface PickedRoad {
  edgeId: string;
  edgeName: string | null;
  at: [number, number];
}

/** Only roads the live simulation has can take an incident or a dispatch. */
// One entry per physical road: OSM two-way roads are two edges ("123" and
// "-123"), which listed every street twice.
const LIVE_ROADS = [
  ...new Map(
    roadEdges
      .filter((e) => e.city === LIVE_CITY)
      .sort((a, b) => Number(a.id.startsWith("-")) - Number(b.id.startsWith("-")))
      .map((e) => [e.id.replace(/^-/, ""), e] as const),
  ).values(),
]
  .map((e) => ({ edge: e, label: roadLabel(e), haystack: `${roadLabel(e)} ${e.id}`.toLowerCase() }))
  .sort((a, b) => a.label.localeCompare(b.label) || b.edge.lengthM - a.edge.lengthM);

/**
 * "Where to?": a search field over the live city's roads, with a button to
 * pick the road on the map instead -- the two ways Apple and Google Maps let
 * you set a destination. Replaces the native <select> of every road id,
 * which looked out of place and listed hundreds of unnamed segments.
 */
export function RoadField({
  value,
  picking,
  onPickOnMap,
  onChange,
  placeholder = "Search roads",
}: {
  value: PickedRoad | null;
  picking: boolean;
  onPickOnMap: () => void;
  onChange: (road: PickedRoad | null) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (q ? LIVE_ROADS.filter((r) => r.haystack.includes(q)) : LIVE_ROADS).slice(0, 7);
  }, [query]);

  const choose = (i: number) => {
    const r = results[i];
    if (!r) return;
    const mid = r.edge.path[Math.floor(r.edge.path.length / 2)]!;
    onChange({ edgeId: r.edge.id, edgeName: r.edge.name, at: [mid[0], mid[1]] });
    setQuery("");
    setOpen(false);
  };

  if (value) {
    const edge = roadEdges.find((e) => e.id === value.edgeId);
    return (
      <div className="flex items-center gap-3 rounded-2xl bg-surface-fill px-3 py-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-status-critical text-white [&_svg]:size-4">
          <MapPin />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-medium leading-tight">{roadLabel(value.edgeId)}</p>
          <p className="truncate text-[12px] text-muted-foreground">
            {cityById.get(LIVE_CITY)?.name}
            {edge ? ` · ${edge.numLanes} lane${edge.numLanes === 1 ? "" : "s"} · ${Math.round(edge.lengthM)} m` : ""}
          </p>
        </div>
        <button
          type="button"
          aria-label="Change location"
          onClick={() => {
            onChange(null);
            window.setTimeout(() => inputRef.current?.focus(), 0);
          }}
          className="grid size-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-4"
        >
          <X />
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex gap-2">
        <label className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-[12px] bg-surface-fill px-3 focus-within:ring-2 focus-within:ring-ring/60">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-label="Road"
            value={query}
            placeholder={placeholder}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              setOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                choose(active);
              } else if (e.key === "Escape") {
                setOpen(false);
              }
            }}
            className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground focus-visible:outline-none"
          />
        </label>
        <button
          type="button"
          onClick={onPickOnMap}
          aria-pressed={picking}
          title="Pick the road on the map"
          className={cn(
            "flex h-11 shrink-0 items-center gap-1.5 rounded-[12px] px-3 text-[14px] font-medium transition-colors [&_svg]:size-4",
            picking ? "bg-primary text-primary-foreground" : "bg-surface-fill text-primary hover:bg-muted",
          )}
        >
          <Crosshair />
          Map
        </button>
      </div>
      {picking && (
        <p className="mt-1.5 px-1 text-[12px] text-primary">Click the road on the map…</p>
      )}
      {open && !picking && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="mt-2 max-h-64 overflow-y-auto rounded-2xl bg-surface-fill p-1"
        >
          {results.map((r, i) => (
            <li
              key={r.edge.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(i);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2",
                i === active && "bg-surface-raised shadow-elevation-1",
              )}
            >
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground [&_svg]:size-3.5">
                <MapPin />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] font-medium">{r.label}</span>
                <span className="block truncate text-[12px] text-muted-foreground">
                  {r.edge.numLanes} lane{r.edge.numLanes === 1 ? "" : "s"} · {Math.round(r.edge.lengthM)} m ·{" "}
                  {Math.round(r.edge.speedLimitMps * 3.6)} km/h
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
