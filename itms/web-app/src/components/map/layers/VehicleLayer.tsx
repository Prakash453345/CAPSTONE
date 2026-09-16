import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { Feature, FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useTrafficStore } from "@/store/trafficStore";
import { useMapStore } from "@/store/mapStore";
import { VEHICLE_COLOR } from "@/components/map/mapColors";
import { angleDelta } from "@/utils/geo";
import type { Vehicle, VehicleType } from "@/types";

const SRC = "vehicles";
const ICON = "vehicles-icon";
const RING = "vehicles-selected";

interface Frame {
  lng: number;
  lat: number;
  heading: number;
  type: Vehicle["type"];
  speed: number;
}

function toFeature(id: string, f: Frame): Feature<Point> {
  return {
    type: "Feature",
    id,
    properties: {
      id,
      type: f.type,
      heading: f.heading,
      speed: Math.round(f.speed),
    },
    geometry: { type: "Point", coordinates: [f.lng, f.lat] },
  };
}

/** A small upward-pointing arrowhead, filled with `color`, as an <img>-ready bitmap. */
function makeArrow(color: string, size = 18): ImageData {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");
  if (!ctx) return new ImageData(size, size);
  const m = size / 2;
  ctx.beginPath();
  ctx.moveTo(m, size * 0.12);
  ctx.lineTo(size * 0.84, size * 0.86);
  ctx.lineTo(m, size * 0.66);
  ctx.lineTo(size * 0.16, size * 0.86);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineJoin = "round";
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(6,9,14,0.9)";
  ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}

/**
 * Vehicles as a single GeoJSON source, re-interpolated every animation frame so
 * markers glide between the ~1 Hz snapshots instead of teleporting (spec §8/§14).
 * Rendered as small rotated arrowheads (heading + type colour) — no glyphs, no
 * per-vehicle DOM.
 */
export function VehicleLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const setSelectedVehicle = useMapStore((s) => s.setSelectedVehicle);
  const vehicles = useTrafficStore((s) => s.vehicles);

  const prev = useRef(new Map<string, Frame>());
  const target = useRef(new Map<string, Frame>());
  const updatedAt = useRef(performance.now());
  const interval = useRef(1000);
  const raf = useRef<number>(0);

  // --- one-time layer setup -------------------------------------------------
  useEffect(() => {
    const icons: Record<VehicleType, string> = {
      car: "veh-car",
      bus: "veh-bus",
      truck: "veh-truck",
      ambulance: "veh-amb",
    };
    for (const [type, name] of Object.entries(icons) as [VehicleType, string][]) {
      if (!map.hasImage(name)) {
        map.addImage(name, makeArrow(VEHICLE_COLOR[type]), { pixelRatio: 2 });
      }
    }

    if (map.getSource(SRC)) return;
    const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
    map.addSource(SRC, { type: "geojson", data: empty });

    map.addLayer({
      id: RING,
      type: "circle",
      source: SRC,
      filter: ["==", ["get", "id"], "__none__"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 7, 17, 13],
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-color": "#5fd0ff",
        "circle-stroke-width": 2,
      },
    });

    map.addLayer({
      id: ICON,
      type: "symbol",
      source: SRC,
      layout: {
        "icon-image": [
          "match",
          ["get", "type"],
          "car",
          "veh-car",
          "bus",
          "veh-bus",
          "truck",
          "veh-truck",
          "veh-car",
        ],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 12, 0.5, 17, 1.05],
        "icon-rotate": ["get", "heading"],
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
    });

    const onClick = (e: MapMouseEvent) => {
      const hits = map.queryRenderedFeatures(e.point, { layers: [ICON] });
      const id = hits[0]?.properties?.id as string | undefined;
      setSelectedVehicle(id ?? null);
      map.setFilter(RING, ["==", ["get", "id"], id ?? "__none__"]);
    };
    const onEnter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const onLeave = () => {
      map.getCanvas().style.cursor = "";
    };
    map.on("click", ICON, onClick);
    map.on("mouseenter", ICON, onEnter);
    map.on("mouseleave", ICON, onLeave);

    return () => {
      cancelAnimationFrame(raf.current);
      map.off("click", ICON, onClick);
      map.off("mouseenter", ICON, onEnter);
      map.off("mouseleave", ICON, onLeave);
      for (const id of [ICON, RING]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map, setSelectedVehicle]);

  // --- visibility --------------------------------------------------------
  useEffect(() => {
    const v = visible ? "visible" : "none";
    for (const id of [ICON, RING])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  // --- ingest a new snapshot -------------------------------------------
  useEffect(() => {
    const now = performance.now();
    interval.current = Math.min(2000, Math.max(200, now - updatedAt.current));
    updatedAt.current = now;

    prev.current = new Map(target.current);

    const nextTarget = new Map<string, Frame>();
    for (const v of vehicles) {
      nextTarget.set(v.id, {
        lng: v.longitude,
        lat: v.latitude,
        heading: v.heading,
        type: v.type,
        speed: v.speed,
      });
    }
    target.current = nextTarget;
  }, [vehicles]);

  // --- animation loop -------------------------------------------------
  useEffect(() => {
    const tick = () => {
      const src = map.getSource(SRC) as GeoJSONSource | undefined;
      if (src) {
        const f = prefersReducedMotion() ? 1 : Math.min(
          1,
          (performance.now() - updatedAt.current) / interval.current,
        );
        const features: Feature<Point>[] = [];
        for (const [id, t] of target.current) {
          const p = prev.current.get(id);
          features.push(
            p
              ? toFeature(id, {
                  lng: p.lng + (t.lng - p.lng) * f,
                  lat: p.lat + (t.lat - p.lat) * f,
                  heading: p.heading + angleDelta(p.heading, t.heading) * f,
                  type: t.type,
                  speed: t.speed,
                })
              : toFeature(id, t),
          );
        }
        src.setData({ type: "FeatureCollection", features });
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [map]);

  return null;
}
