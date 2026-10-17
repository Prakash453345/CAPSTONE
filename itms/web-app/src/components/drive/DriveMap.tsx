import { useEffect, useRef, useState } from "react";
import maplibregl, { Map as MapLibreMap, type GeoJSONSource, type LngLatBoundsLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { Locate, Minus, Plus, Route as RouteIcon } from "lucide-react";
import { initialStyle } from "@/components/map/mapStyle";
import { Basemap } from "@/components/map/Basemap";
import { MapContext, useMapInstance } from "@/components/map/MapContext";
import { RoadLayer } from "@/components/map/layers/RoadLayer";
import { SignalLayer } from "@/components/map/layers/SignalLayer";
import { AnomalyLayer } from "@/components/map/layers/AnomalyLayer";
import { EmergencyVehicleLayer } from "@/components/map/layers/EmergencyVehicleLayer";
import { isMapAlive } from "@/components/map/mapSafe";
import { EV_ROUTE_COLOR } from "@/components/map/mapColors";
import { networkBounds } from "@/data/network";
import { slicePlan } from "@/drive/plan";
import type { Mission } from "@/drive/useMission";
import { useDriveStore } from "@/store/driveStore";
import { useThemeStore } from "@/store/themeStore";
import { prefersReducedMotion } from "@/utils/motion";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/utils/cn";

const FIT_NETWORK: LngLatBoundsLike = [
  [networkBounds.minLng, networkBounds.minLat],
  [networkBounds.maxLng, networkBounds.maxLat],
];

const FOLLOW = { zoom: 16.8, pitch: 50 } as const;

/**
 * Where the vehicle should sit: in the part of the map the panels leave free,
 * a little below its middle so the road ahead fills the view. On a wide
 * screen the panels are a column on the left; on a phone they are a banner on
 * top and a band of cards along the bottom.
 */
function followPadding(map: MapLibreMap) {
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  return w >= 1024
    ? { top: 160, bottom: 140, left: 440, right: 90 }
    : { top: 250, bottom: Math.round(h * 0.34 + 120), left: 0, right: 0 };
}

const SRC = "drive-route";
const POINTS = "drive-points";
const CASING = "drive-route-casing";
const DONE = "drive-route-done";
const AHEAD = "drive-route-ahead";
const DEST_RING = "drive-dest-ring";
const DEST_DOT = "drive-dest-dot";
const TURN_DOT = "drive-turn-dot";

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };

/** The route being driven: grey behind you, green ahead, with the next turn and destination marked. */
function DriveRouteLayer({ mission }: { mission: Mission | null }) {
  const map = useMapInstance();

  useEffect(() => {
    const dark = useThemeStore.getState().resolved === "dark";
    if (!map.getSource(SRC)) {
      map.addSource(SRC, { type: "geojson", data: empty });
      map.addSource(POINTS, { type: "geojson", data: empty });
      const layout = { "line-cap": "round", "line-join": "round" } as const;
      map.addLayer({
        id: CASING,
        type: "line",
        source: SRC,
        filter: ["==", ["get", "part"], "ahead"],
        layout,
        paint: {
          // Darker than the road beneath in either theme, so the route outlines itself.
          "line-color": dark ? "#04140c" : "#0b6b37",
          "line-opacity": 0.92,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 9, 17, 22],
        },
      });
      map.addLayer({
        id: DONE,
        type: "line",
        source: SRC,
        filter: ["==", ["get", "part"], "done"],
        layout,
        paint: {
          "line-color": "#8794a8",
          "line-opacity": 0.55,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 17, 8],
        },
      });
      map.addLayer({
        id: AHEAD,
        type: "line",
        source: SRC,
        filter: ["==", ["get", "part"], "ahead"],
        layout,
        paint: {
          "line-color": EV_ROUTE_COLOR,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 5, 17, 14],
        },
      });
      map.addLayer({
        id: DEST_RING,
        type: "circle",
        source: POINTS,
        filter: ["==", ["get", "kind"], "destination"],
        paint: { "circle-radius": 13, "circle-color": "#e5484d", "circle-opacity": 0.28 },
      });
      map.addLayer({
        id: DEST_DOT,
        type: "circle",
        source: POINTS,
        filter: ["==", ["get", "kind"], "destination"],
        paint: { "circle-radius": 7, "circle-color": "#e5484d", "circle-stroke-width": 3, "circle-stroke-color": "#ffffff" },
      });
      map.addLayer({
        id: TURN_DOT,
        type: "circle",
        source: POINTS,
        filter: ["==", ["get", "kind"], "turn"],
        paint: { "circle-radius": 7, "circle-color": "#ffffff", "circle-stroke-width": 3, "circle-stroke-color": EV_ROUTE_COLOR },
      });
    }
    return () => {
      if (!isMapAlive(map)) return;
      for (const id of [TURN_DOT, DEST_DOT, DEST_RING, AHEAD, DONE, CASING]) if (map.getLayer(id)) map.removeLayer(id);
      for (const id of [POINTS, SRC]) if (map.getSource(id)) map.removeSource(id);
    };
  }, [map]);

  useEffect(() => {
    if (!isMapAlive(map)) return;
    const lines = map.getSource(SRC) as GeoJSONSource | undefined;
    const points = map.getSource(POINTS) as GeoJSONSource | undefined;
    if (!lines || !points) return;
    const plan = mission?.plan;
    if (!mission || !plan) {
      lines.setData(empty);
      points.setData(empty);
      return;
    }
    const along = mission.alongM;
    const lineFeatures: Feature[] = [
      { type: "Feature", properties: { part: "ahead" }, geometry: { type: "LineString", coordinates: slicePlan(plan, along, plan.totalM) } },
    ];
    // Before the vehicle has moved there is no "done" part, and a zero-length
    // line in the source stops the whole route from drawing.
    if (along > 1) {
      lineFeatures.unshift({ type: "Feature", properties: { part: "done" }, geometry: { type: "LineString", coordinates: slicePlan(plan, 0, along) } });
    }
    lines.setData({ type: "FeatureCollection", features: lineFeatures });
    const end = plan.coords[plan.coords.length - 1]!;
    const pointFeatures: Feature[] = [{ type: "Feature", properties: { kind: "destination" }, geometry: { type: "Point", coordinates: end } }];
    const next = mission.next;
    if (next && next.kind !== "arrive") {
      const at = slicePlan(plan, next.atM, next.atM)[0]!;
      pointFeatures.push({ type: "Feature", properties: { kind: "turn" }, geometry: { type: "Point", coordinates: at } });
    }
    points.setData({ type: "FeatureCollection", features: pointFeatures });
  }, [map, mission]);

  return null;
}

/** Keeps the vehicle centred while following; fits the whole route before the run starts. */
function DriveCamera({ mission }: { mission: Mission | null }) {
  const map = useMapInstance();
  const camera = useDriveStore((s) => s.camera);
  const setCamera = useDriveStore((s) => s.setCamera);
  const fitted = useRef<string>("");

  // A drag, pinch or scroll by the crew hands the camera back to them.
  useEffect(() => {
    const release = (e: { originalEvent?: unknown }) => {
      if (e.originalEvent) setCamera("free");
    };
    map.on("dragstart", release);
    map.on("zoomstart", release);
    map.on("rotatestart", release);
    return () => {
      if (!isMapAlive(map)) return;
      map.off("dragstart", release);
      map.off("zoomstart", release);
      map.off("rotatestart", release);
    };
  }, [map, setCamera]);

  const plan = mission?.plan;
  const routeKey = plan ? `${mission?.request.id}:${plan.edgeIds.join(",")}` : "";
  const underway = Boolean(mission?.underway && !mission.arrived);

  // Before the vehicle is moving (or when the route changes), show the whole route.
  useEffect(() => {
    if (!plan || underway || fitted.current === routeKey) return;
    fitted.current = routeKey;
    const lngs = plan.coords.map((c) => c[0]);
    const lats = plan.coords.map((c) => c[1]);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: followPadding(map), duration: prefersReducedMotion() ? 0 : 900, maxZoom: 17 },
    );
  }, [map, plan, routeKey, underway]);

  // Numbers, not the position array: a new array every update would restart the
  // easing each time even though the vehicle has not moved.
  const lng = mission?.position?.[0];
  const lat = mission?.position?.[1];
  const heading = mission?.headingDeg;
  useEffect(() => {
    if (lng == null || lat == null || !underway || camera !== "follow") return;
    map.easeTo({
      center: [lng, lat],
      bearing: heading ?? map.getBearing(),
      zoom: FOLLOW.zoom,
      pitch: FOLLOW.pitch,
      padding: followPadding(map),
      duration: prefersReducedMotion() ? 0 : 900,
      easing: (t) => t,
      essential: false,
    });
  }, [map, lng, lat, heading, underway, camera]);

  return null;
}

function MapButtons({ mission }: { mission: Mission | null }) {
  const map = useMapInstance();
  const camera = useDriveStore((s) => s.camera);
  const setCamera = useDriveStore((s) => s.setCamera);
  const plan = mission?.plan;
  const btn =
    "grid size-11 place-items-center rounded-xl bg-surface-raised text-foreground shadow-elevation-2 transition-colors hover:bg-muted active:scale-95 [&_svg]:size-5";

  return (
    <div className="pointer-events-auto absolute bottom-28 right-3 z-10 flex flex-col gap-2 sm:bottom-24">
      {mission?.underway && camera === "free" && (
        <button type="button" aria-label="Follow my vehicle" title="Follow my vehicle" className={cn(btn, "bg-primary text-primary-foreground hover:bg-primary/90")} onClick={() => setCamera("follow")}>
          <Locate />
        </button>
      )}
      {plan && (
        <button
          type="button"
          aria-label="Show the whole route"
          title="Show the whole route"
          className={btn}
          onClick={() => {
            setCamera("free");
            const lngs = plan.coords.map((c) => c[0]);
            const lats = plan.coords.map((c) => c[1]);
            map.fitBounds(
              [
                [Math.min(...lngs), Math.min(...lats)],
                [Math.max(...lngs), Math.max(...lats)],
              ],
              { padding: followPadding(map), pitch: 0, bearing: 0, duration: prefersReducedMotion() ? 0 : 800, maxZoom: 17 },
            );
          }}
        >
          <RouteIcon />
        </button>
      )}
      <div className="flex flex-col overflow-hidden rounded-xl bg-surface-raised shadow-elevation-2">
        <button type="button" aria-label="Zoom in" className="grid size-11 place-items-center hover:bg-muted [&_svg]:size-5" onClick={() => map.zoomIn()}>
          <Plus />
        </button>
        <span className="h-px bg-border" />
        <button type="button" aria-label="Zoom out" className="grid size-11 place-items-center hover:bg-muted [&_svg]:size-5" onClick={() => map.zoomOut()}>
          <Minus />
        </button>
      </div>
    </div>
  );
}

/**
 * The Drive page's map: the console's basemap and live layers (congestion,
 * signals, incidents, emergency units) with the crew's own route on top, and
 * a camera that follows the vehicle.
 */
export function DriveMap({ mission, className }: { mission: Mission | null; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let disposed = false;
    let instance: MapLibreMap | null = null;

    const create = () => {
      if (disposed || instance) return;
      try {
        instance = new maplibregl.Map({
          container: el,
          style: initialStyle(useThemeStore.getState().resolved),
          bounds: FIT_NETWORK,
          fitBoundsOptions: { padding: 48 },
          attributionControl: { compact: true },
          dragRotate: true,
          maxZoom: 19,
          minZoom: 11,
          fadeDuration: 0,
        });
      } catch {
        disposed = true;
        setMapError("The map could not start. Turn on hardware acceleration (WebGL) and reload. Your route and instructions still work without it.");
        return;
      }
      instance.getCanvas().setAttribute("aria-label", "Route map. Drag to look around; the follow button brings it back to your vehicle.");
      const created = instance;
      const markReady = () => !disposed && setReady(true);
      if (created.isStyleLoaded()) markReady();
      else created.once("style.load", markReady);
      setMap(created);
    };

    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0 && box.height > 0) {
        if (instance) instance.resize();
        else create();
      }
    });
    ro.observe(el);
    if (el.clientWidth > 0 && el.clientHeight > 0) create();

    return () => {
      disposed = true;
      ro.disconnect();
      // Same ordering rule as TrafficMap: let the layer components clean up
      // against a live map first, then retire it.
      const retiring = instance;
      queueMicrotask(() => retiring?.remove());
    };
  }, []);

  return (
    <div className={cn("absolute inset-0 overflow-hidden", className)}>
      {/* Inline: maplibre-gl.css sets .maplibregl-map { position: relative } and, on a
          lazy route, loads after Tailwind and would collapse the map (see TrafficMap). */}
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      {mapError && (
        <div className="absolute inset-0 z-20 grid place-items-center bg-background p-8">
          <p role="alert" className="max-w-sm text-center text-sm leading-relaxed text-muted-foreground">
            {mapError}
          </p>
        </div>
      )}
      {!ready && !mapError && (
        <div className="absolute inset-0 grid place-items-center bg-background">
          <Skeleton className="h-40 w-64" />
        </div>
      )}
      {map && ready && (
        <MapContext.Provider value={map}>
          <Basemap />
          <RoadLayer visible />
          <DriveRouteLayer mission={mission} />
          <SignalLayer visible />
          <AnomalyLayer visible />
          <EmergencyVehicleLayer visible />
          <DriveCamera mission={mission} />
          <MapButtons mission={mission} />
        </MapContext.Provider>
      )}
    </div>
  );
}
