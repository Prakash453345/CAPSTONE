import { useEffect, useRef, useState } from "react";
import maplibregl, { Map as MapLibreMap, type MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { initialStyle } from "@/components/map/mapStyle";
import { Basemap } from "@/components/map/Basemap";
import { useThemeStore } from "@/store/themeStore";
import { MapContext } from "@/components/map/MapContext";
import { MapControls } from "@/components/map/MapControls";
import { MapLegend } from "@/components/map/MapLegend";
import { MapSearch } from "@/components/map/MapSearch";
import { RoadHighlight } from "@/components/map/RoadHighlight";
import { RoadPlaceCard } from "@/components/map/RoadPlaceCard";
import { WeatherLayer } from "@/components/map/WeatherLayer";
import { WeatherChip } from "@/components/map/WeatherChip";
import { MapChromeContext, createMapChromeStore } from "@/store/mapChromeStore";
import { useStore } from "zustand";
import { MapNewMenu } from "@/components/map/MapNewMenu";
import { RoadLayer } from "@/components/map/layers/RoadLayer";
import { VehicleLayer } from "@/components/map/layers/VehicleLayer";
import { SignalLayer } from "@/components/map/layers/SignalLayer";
import { IncidentLayer } from "@/components/map/layers/IncidentLayer";
import { AnomalyLayer } from "@/components/map/layers/AnomalyLayer";
import { EmergencyRouteLayer } from "@/components/map/layers/EmergencyRouteLayer";
import { EmergencyVehicleLayer } from "@/components/map/layers/EmergencyVehicleLayer";
import {
  CreateAnomalyPanel,
  type AnomalyTarget,
} from "@/components/map/CreateAnomalyPanel";
import { EmergencyPanel } from "@/components/map/EmergencyPanel";
import { UploadClipPanel } from "@/components/map/UploadClipPanel";
import { FollowCamera } from "@/components/map/FollowCamera";
import { useMapStore } from "@/store/mapStore";
import { useTransitionStore } from "@/store/transitionStore";
import { useIncidentStore } from "@/store/incidentStore";
import { selectSelectedRequest, useEmergencyStore } from "@/store/emergencyStore";
import { networkBounds, nearestEdge } from "@/data/network";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/utils/cn";
import { CITIES_LABEL } from "@/data/city";

const FIT_BOUNDS: [number, number, number, number] = [
  networkBounds.minLng,
  networkBounds.minLat,
  networkBounds.maxLng,
  networkBounds.maxLat,
];

export function TrafficMap({
  className,
  fullscreen = false,
  onExitFullscreen,
}: {
  className?: string;
  /** Rendered by the full-screen map route: controls offer "Exit full screen". */
  fullscreen?: boolean;
  /** Leaves full screen: shown as the search pill's back arrow and the exit control. */
  onExitFullscreen?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [tileError, setTileError] = useState(false);
  // This map's own sheet/selection state, so split view's two maps are independent.
  const [chrome] = useState(createMapChromeStore);

  const activeLayers = useMapStore((s) => s.activeLayers);
  const focus = useMapStore((s) => s.focus);
  const interactionMode = useMapStore((s) => s.interactionMode);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const setDraftPoint = useEmergencyStore((s) => s.setDraftPoint);

  const [pendingTarget, setPendingTarget] = useState<AnomalyTarget | null>(null);
  const [clipTarget, setClipTarget] = useState<AnomalyTarget | null>(null);
  const [pickHint, setPickHint] = useState<string | null>(null);
  const creatingAnomaly = interactionMode === "create-anomaly";

  // --- create / destroy the map ------------------------------------------
  // Creation is deferred until the container has a non-zero size: MapLibre
  // created in a 0x0 box never finishes loading and stays blank.
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
        bounds: FIT_BOUNDS,
        fitBoundsOptions: { padding: 64 },
        attributionControl: { compact: true },
        dragRotate: true,
        maxZoom: 19,
        minZoom: 11,
        fadeDuration: 0,
      });
      } catch {
        disposed = true;
        setMapError("The map could not initialize. Enable WebGL / hardware acceleration, then reload. Road and signal lists remain available in Traffic Management.");
        return;
      }
      // The attribution only turns compact (and auto-expands) once the first
      // source arrives, since the map starts with none; fold it that once.
      const created = instance;
      const foldWhenCompact = () => {
        if (!el.querySelector(".maplibregl-ctrl-attrib.maplibregl-compact")) return;
        foldAttribution(el.clientWidth);
        created.off("sourcedata", foldWhenCompact);
      };
      created.on("sourcedata", foldWhenCompact);
      instance.addControl(new maplibregl.ScaleControl({ maxWidth: 88, unit: "metric" }), "bottom-left");
      instance.on("error", (e) => {
        if (disposed) return;
        console.warn("Map resource error:", e.error?.message ?? e);
        setTileError(true);
      });
      instance.getCanvas().setAttribute("aria-label", `${CITIES_LABEL} traffic map. Use arrow keys to pan, plus and minus to zoom.`);
      // Arriving via the globe cinematic: start a little further out and
      // finish the dive's zoom once the overlay lifts, so the two read as
      // one continuous move.
      if (useTransitionStore.getState().active) {
        const target = instance.getZoom();
        const map = instance;
        map.jumpTo({ zoom: Math.max(map.getMinZoom(), target - 1.6) });
        const arrive = () => {
          if (disposed) return;
          map.easeTo({
            zoom: target,
            duration: 2400,
            easing: (t) => 1 - Math.pow(1 - t, 3),
            essential: false,
          });
        };
        const unsub = useTransitionStore.subscribe((s) => {
          if (!s.active) {
            unsub();
            arrive();
          }
        });
        map.once("remove", unsub);
      }
      const markReady = () => {
        if (!disposed) setReady(true);
      };
      // Style readiness does not wait on third-party raster tile requests.
      if (instance.isStyleLoaded()) markReady();
      else instance.once("style.load", markReady);
      setMap(instance);
    };

    // On narrow maps (split view, phones) the attribution folds into its (i)
    // button so it can't sit on the scale bar; tapping (i) still shows it.
    // Same class MapLibre itself drops on the first drag (_updateCompactMinimize).
    const foldAttribution = (width: number) => {
      if (width >= 480) return;
      el.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
    };

    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0 && box.height > 0) {
        if (instance) instance.resize();
        else create();
        foldAttribution(box.width);
      }
    });
    ro.observe(el);

    // Fast path: element already has a size on first layout.
    if (el.clientWidth > 0 && el.clientHeight > 0) create();

    return () => {
      disposed = true;
      ro.disconnect();
      // React runs parent passive cleanup before descendant layer cleanup.
      // Keep the style alive until those children have removed sources, listeners
      // and animation frames; destroying it first crashes every route change.
      const retiringMap = instance;
      queueMicrotask(() => retiringMap?.remove());
    };
  }, []);

  // --- react to focus requests -----------------------------------------
  useEffect(() => {
    if (!map || !ready || focus.nonce === 0) return;
    map.flyTo({
      center: [focus.center.longitude, focus.center.latitude],
      zoom: focus.zoom,
      duration: 900,
      essential: false,
    });
  }, [map, ready, focus]);

  // --- map click resolves to a SUMO edge, for anomaly + route-point picking --
  const picking =
    interactionMode === "create-anomaly" ||
    interactionMode === "pick-source" ||
    interactionMode === "pick-destination";

  useEffect(() => {
    if (!map || !ready) return;
    const canvas = map.getCanvas();
    if (!picking) {
      canvas.style.cursor = "";
      return;
    }
    canvas.style.cursor = "crosshair";
    const onClick = (e: MapMouseEvent) => {
      const hit = nearestEdge([e.lngLat.lng, e.lngLat.lat], 45);
      if (!hit) {
        setPickHint("Click directly on a road");
        window.setTimeout(() => setPickHint(null), 1600);
        return;
      }
      setPickHint(null);
      const point = { edgeId: hit.edge.id, edgeName: hit.edge.name, at: hit.snapped };
      if (interactionMode === "create-anomaly") {
        setPendingTarget(point);
      } else if (interactionMode === "pick-source") {
        setDraftPoint("source", point);
        setInteractionMode("idle");
      } else if (interactionMode === "pick-destination") {
        setDraftPoint("destination", point);
        setInteractionMode("idle");
      }
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
      canvas.style.cursor = "";
    };
  }, [map, ready, picking, interactionMode, setDraftPoint, setInteractionMode]);

  // Idle clicks select a road and open its place card, unless they land on
  // a clickable overlay (anomaly, incident, signal, vehicle), which own the
  // click. Clicking empty map clears the selection, as in Google Maps.
  const selectRoad = useStore(chrome, (s) => s.selectRoad);
  const selectedRoad = useStore(chrome, (s) => s.selectedRoad);
  useEffect(() => {
    if (!map || !ready || picking) return;
    const overlays = [
      "anomaly-mark-dot",
      "incidents-dot",
      "signals-dot",
      "vehicles-icon",
      "em-vehicles-icon",
    ];
    const onClick = (e: MapMouseEvent) => {
      const layers = overlays.filter((id) => map.getLayer(id));
      if (layers.length && map.queryRenderedFeatures(e.point, { layers }).length) return;
      const hit = nearestEdge([e.lngLat.lng, e.lngLat.lat], 25);
      selectRoad(hit ? { edgeId: hit.edge.id, at: hit.snapped } : null);
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
    };
  }, [map, ready, picking, selectRoad]);

  const emergencyDraft = useEmergencyStore((s) => s.draft);
  const emergencySelected = useEmergencyStore(selectSelectedRequest);
  const operatorPanelOpen =
    creatingAnomaly || clipTarget !== null || Boolean(emergencyDraft || emergencySelected);
  const panelOpen = operatorPanelOpen || selectedRoad !== null;

  const exitCreate = () => {
    setPendingTarget(null);
    setPickHint(null);
    setInteractionMode("idle");
  };

  return (
    <MapChromeContext.Provider value={chrome}>
      <div className={cn("absolute inset-0 overflow-hidden", className)}>
        {/* Inline, not Tailwind's "absolute inset-0": maplibre-gl.css sets
            .maplibregl-map { position: relative } at equal specificity, and since
            routes are lazy it loads after Tailwind and wins, collapsing the map
            to 0 px tall. Inline style can't lose that ordering race. */}
        <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

        {mapError && <div className="absolute inset-0 z-20 grid place-items-center bg-background p-8"><p role="alert" className="max-w-sm text-center text-sm leading-relaxed text-muted-foreground">{mapError}</p></div>}
        {!ready && !mapError && (
          <div className="absolute inset-0 grid place-items-center bg-background">
            <div className="flex flex-col items-center gap-3">
              <Skeleton className="h-40 w-64" />
              <span className="font-mono text-xs text-muted-foreground">
                loading map…
              </span>
            </div>
          </div>
        )}

        {map && ready && (
          <MapContext.Provider value={map}>
            <Basemap />
            <RoadLayer visible={activeLayers.has("congestion")} />
            <RoadHighlight />
            <SignalLayer visible={activeLayers.has("signals")} />
            <EmergencyRouteLayer visible={activeLayers.has("emergency")} />
            <EmergencyVehicleLayer visible={activeLayers.has("emergency")} />
            <IncidentLayer visible={activeLayers.has("incidents")} />
            <AnomalyLayer visible={activeLayers.has("anomalies")} />
            <VehicleLayer visible={activeLayers.has("vehicles")} />
            <WeatherLayer visible={activeLayers.has("weather")} />
            <MapControls fullscreen={fullscreen} onExitFullscreen={onExitFullscreen} />
            {/* the route panel covers the map's left edge on wide maps (308px + margin) */}
            <FollowCamera
              leftInset={operatorPanelOpen && (containerRef.current?.clientWidth ?? 0) >= 720 ? 336 : 0}
            />
          </MapContext.Provider>
        )}

        {/* Google-style search row (search pill + chips), panels open below it */}
        <div className="map-action-stack pointer-events-none absolute left-3 top-3 flex flex-col items-start gap-2">
          <div className="flex max-w-full flex-wrap items-start gap-2">
            {map && ready && (
              <MapContext.Provider value={map}>
                <MapSearch onBack={onExitFullscreen} />
              </MapContext.Provider>
            )}
            <div className="map-chip-row flex h-11 max-w-full items-center gap-2">
              <MapNewMenu onCancelAnomaly={exitCreate} />
            </div>
          </div>

          {tileError && ready && (
            <div role="status" className="pointer-events-none max-w-[340px] animate-fade-in rounded-lg bg-surface-raised px-3 py-2 text-[11px] leading-snug text-status-warn shadow-elevation-1">
              Some map resources are unavailable. Bundled road geometry and received telemetry remain visible.
            </div>
          )}

          {creatingAnomaly && !pendingTarget && (
            <div className="pointer-events-none animate-fade-in rounded-full bg-foreground/85 px-3.5 py-1.5 text-xs text-background shadow-elevation-1">
              {pickHint ?? "Click a road to place the anomaly"}
            </div>
          )}

          {pendingTarget && (
            <CreateAnomalyPanel
              target={pendingTarget}
              onClose={exitCreate}
              onCreated={(id) => {
                selectAnomaly(id);
                exitCreate();
              }}
            />
          )}

          <EmergencyPanel part="panel" />

          {clipTarget && !creatingAnomaly && (
            <UploadClipPanel target={clipTarget} onClose={() => setClipTarget(null)} />
          )}

          {!operatorPanelOpen && (
            <RoadPlaceCard
              onCreateAnomaly={(target) => setPendingTarget(target)}
              onUploadClip={(target) => setClipTarget(target)}
            />
          )}
        </div>

        <MapLegend hidden={panelOpen} />
        {activeLayers.has("weather") && <WeatherChip />}
      </div>
    </MapChromeContext.Provider>
  );
}
