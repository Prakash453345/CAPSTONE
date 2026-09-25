import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import { MapPin, Search, TrafficCone, X } from "lucide-react";
import { useMapInstance } from "@/components/map/MapContext";
import { HIGHLIGHT_BLUE } from "@/components/map/mapChrome";
import { roadEdges, signalJunctions, shortJunctionName } from "@/data/network";
import type { LngLat } from "@/utils/geo";
import { cn } from "@/utils/cn";
import { useMapChromeStore } from "@/store/mapChromeStore";

/**
 * Google Maps' search pill, over the TRAFFIX network: roads by name or edge id
 * and signalised junctions. Picking a result flies the camera there and
 * outlines the road in Google blue, the way Maps highlights a searched street.
 */

interface Result {
  key: string;
  kind: "road" | "junction";
  title: string;
  subtitle: string;
  path: LngLat[];
}

const ENTRIES: Result[] = [
  ...roadEdges.map((e) => ({
    key: `road:${e.id}`,
    kind: "road" as const,
    title: e.name ?? `Road ${e.id}`,
    subtitle: `${e.numLanes} lane${e.numLanes === 1 ? "" : "s"} · ${(e.lengthM / 1000).toFixed(2)} km · ${Math.round(e.speedLimitMps * 3.6)} km/h`,
    path: e.path,
  })),
  ...signalJunctions.map((j) => ({
    key: `junction:${j.id}`,
    kind: "junction" as const,
    title: shortJunctionName(j.id),
    subtitle: "Signalised junction",
    path: [[j.lng, j.lat]] as LngLat[],
  })),
];

const SRC = "search-highlight";
const CASING = "search-highlight-casing";
const LINE = "search-highlight-line";

function match(query: string): Result[] {
  const q = query.trim().toLowerCase();
  if (!q) return ENTRIES.slice(0, 6);
  return ENTRIES.filter(
    (r) => r.title.toLowerCase().includes(q) || r.key.toLowerCase().includes(q),
  ).slice(0, 8);
}

export function MapSearch() {
  const map = useMapInstance();
  const [query, setQuery] = useState("");
  const open = useMapChromeStore((s) => s.sheet === "search");
  const openSheet = useMapChromeStore((s) => s.open);
  const closeSheet = useMapChromeStore((s) => s.close);
  const setOpen = (next: boolean) => (next ? openSheet("search") : closeSheet("search"));
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<Result | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const results = useMemo(() => match(query), [query]);

  // Highlight source + layers, drawn above the traffic overlays.
  useEffect(() => {
    if (!map.getSource(SRC)) {
      map.addSource(SRC, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: CASING,
        type: "line",
        source: SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 7, 17, 18], "line-opacity": 0.95 },
      });
      map.addLayer({
        id: LINE,
        type: "line",
        source: SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": HIGHLIGHT_BLUE, "line-width": ["interpolate", ["linear"], ["zoom"], 12, 4, 17, 11] },
      });
    }
    return () => {
      for (const id of [LINE, CASING]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map]);

  useEffect(() => {
    const src = map.getSource(SRC) as GeoJSONSource | undefined;
    src?.setData({
      type: "FeatureCollection",
      features:
        picked && picked.kind === "road"
          ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: picked.path } }]
          : [],
    });
  }, [map, picked]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) closeSheet("search");
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open, closeSheet]);

  const choose = (r: Result) => {
    setPicked(r);
    setQuery(r.title);
    setOpen(false);
    if (r.kind === "junction") {
      map.flyTo({ center: r.path[0], zoom: 17.5, duration: 1200, curve: 1.3, essential: false });
      return;
    }
    const lngs = r.path.map((p) => p[0]);
    const lats = r.path.map((p) => p[1]);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lngs), Math.min(...lats)],
      [Math.max(...lngs), Math.max(...lats)],
    ];
    map.fitBounds(bounds, { padding: 120, maxZoom: 17.5, duration: 1200, essential: false });
  };

  const clear = () => {
    setQuery("");
    setPicked(null);
    setActive(0);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[active]) {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && results.length > 0;

  return (
    <div ref={rootRef} className="pointer-events-auto relative w-[min(340px,100%)] shrink-0">
      {/* The list is in normal flow (not absolute) so the scrolling action
          stack around it grows to fit instead of clipping it. */}
      <div
        className={cn(
          "relative z-[1] flex h-11 items-center gap-1 bg-surface-raised pl-4 pr-1.5 shadow-[0_2px_4px_rgba(0,0,0,0.2),0_-1px_0_rgba(0,0,0,0.02)] transition-[border-radius,box-shadow] duration-200 ease-out",
          showList ? "rounded-t-[22px] shadow-elevation-2" : "rounded-full",
        )}
      >
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search roads"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label="Search the road network"
          className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        {query ? (
          <IconBtn label="Clear search" onClick={clear}>
            <X />
          </IconBtn>
        ) : (
          <IconBtn label="Search" onClick={() => setOpen(true)}>
            <Search />
          </IconBtn>
        )}
      </div>

      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="relative max-h-72 origin-top animate-sheet-in overflow-y-auto rounded-b-[22px] border-t border-border bg-surface-raised py-2 shadow-elevation-2"
        >
          {results.map((r, i) => {
            const Icon = r.kind === "road" ? MapPin : TrafficCone;
            return (
              <li
                key={r.key}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(r);
                }}
                className={cn(
                  "flex cursor-pointer items-center gap-3 px-4 py-2 transition-colors",
                  i === active && "bg-muted",
                )}
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground [&_svg]:size-4">
                  <Icon />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm text-foreground">{r.title}</span>
                  <span className="block truncate text-xs text-muted-foreground">{r.subtitle}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid size-9 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-5"
    >
      {children}
    </button>
  );
}
