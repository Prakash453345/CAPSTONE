import { useEffect, useRef, useState } from "react";
import maplibregl, { Map as MapLibreMap, type MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { AlertTriangle } from "lucide-react";
import { BASE_STYLE } from "@/components/map/mapStyle";
import { MapContext } from "@/components/map/MapContext";
import { MapControls } from "@/components/map/MapControls";
import { MapLegend } from "@/components/map/MapLegend";
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
import { useMapStore } from "@/store/mapStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useEmergencyStore } from "@/store/emergencyStore";
import { networkBounds, nearestEdge } from "@/data/network";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/utils/cn";

const FIT_BOUNDS: [number, number, number, number] = [
  networkBounds.minLng,
  networkBounds.minLat,
  networkBounds.maxLng,
  networkBounds.maxLat,
];

export function TrafficMap({ className }: { className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [tileError, setTileError] = useState(false);

  const activeLayers = useMapStore((s) => s.activeLayers);
  const focus = useMapStore((s) => s.focus);
  const interactionMode = useMapStore((s) => s.interactionMode);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const setDraftPoint = useEmergencyStore((s) => s.setDraftPoint);

  const [pendingTarget, setPendingTarget] = useState<AnomalyTarget | null>(null);
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
        style: BASE_STYLE,
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
      instance.on("error", () => { if (!disposed) setTileError(true); });
      instance.getCanvas().setAttribute("aria-label", "Vijayawada traffic map. Use arrow keys to pan, plus and minus to zoom.");
      const markReady = () => {
        if (!disposed) setReady(true);
      };
      // Style readiness does not wait on third-party raster tile requests.
      if (instance.isStyleLoaded()) markReady();
      else instance.once("style.load", markReady);
      setMap(instance);
    };

    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0 && box.height > 0) {
        if (instance) instance.resize();
        else create();
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

  const exitCreate = () => {
    setPendingTarget(null);
    setPickHint(null);
    setInteractionMode("idle");
  };

  return (
    <div className={cn("absolute inset-0 overflow-hidden", className)}>
      <div ref={containerRef} className="absolute inset-0" />

      {mapError && <div className="absolute inset-0 z-20 grid place-items-center bg-background p-8"><p role="alert" className="max-w-sm text-center text-sm leading-relaxed text-muted-foreground">{mapError}</p></div>}
      {tileError && ready && <div role="status" className="pointer-events-none absolute bottom-16 left-3 right-3 z-10 rounded-md bg-surface/95 p-2 text-[10px] text-status-warn">Some map resources are unavailable. Bundled road geometry and received telemetry remain visible.</div>}
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
          <RoadLayer visible={activeLayers.has("congestion")} />
          <SignalLayer visible={activeLayers.has("signals")} />
          <EmergencyRouteLayer visible={activeLayers.has("emergency")} />
          <EmergencyVehicleLayer visible={activeLayers.has("emergency")} />
          <IncidentLayer visible={activeLayers.has("incidents")} />
          <AnomalyLayer visible={activeLayers.has("anomalies")} />
          <VehicleLayer visible={activeLayers.has("vehicles")} />
          <MapControls />
        </MapContext.Provider>
      )}

      {/* Create Anomaly toolbar + contextual panel (top-left) */}
      <div className="map-action-stack pointer-events-none absolute left-3 top-3 flex flex-col items-start gap-2">
        <button
          type="button"
          onClick={() =>
            creatingAnomaly ? exitCreate() : setInteractionMode("create-anomaly")
          }
          className={cn(
            "pointer-events-auto flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-panel backdrop-blur-sm transition-colors",
            creatingAnomaly
              ? "border-primary/70 bg-primary/20 text-foreground"
              : "border-border bg-surface/90 text-muted-foreground hover:text-foreground",
          )}
        >
          <AlertTriangle className="size-3.5" />
          {creatingAnomaly ? "Cancel" : "Create anomaly"}
        </button>

        {creatingAnomaly && !pendingTarget && (
          <div className="pointer-events-none rounded-md border border-border bg-surface/90 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-panel backdrop-blur-sm">
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

        <EmergencyPanel />
      </div>

      <MapLegend />
    </div>
  );
}
