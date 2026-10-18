import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { Feature, FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { isMapAlive } from "@/components/map/mapSafe";
import { useTrafficStore } from "@/store/trafficStore";
import { useMapStore } from "@/store/mapStore";
import { VEHICLE_COLOR } from "@/components/map/mapColors";
import {
  VEHICLE_ICON_ID,
  makeVehicleIcon,
  upsertMapImage,
} from "@/components/map/mapIcons";
import { angleDelta } from "@/utils/geo";
import type { Vehicle, VehicleType } from "@/types";

const SRC = "vehicles";
const ICON = "vehicles-icon";
const RING = "vehicles-selected";
const BACKPLATE = "vehicles-backplate";

interface Frame {
  lng: number;
  lat: number;
  heading: number;
  type: Vehicle["type"];
  speed: number;
}

function toFeature(id: string, f: Frame, selected: boolean): Feature<Point> {
  return {
    type: "Feature",
    id,
    properties: {
      id,
      vtype: f.type,
      color: VEHICLE_COLOR[f.type],
      heading: f.heading,
      speed: Math.round(f.speed),
      selected: selected ? 1 : 0,
    },
    geometry: { type: "Point", coordinates: [f.lng, f.lat] },
  };
}

/**
 * Vehicles as a single GeoJSON source, re-interpolated every animation frame so
 * markers glide between the ~1 Hz snapshots instead of teleporting (spec §8/§14).
 * Rendered as MapLibre symbol sprites (stylized top-down silhouettes) — no
 * glyphs, no per-vehicle DOM.
 */
export function VehicleLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const setSelectedVehicle = useMapStore((s) => s.setSelectedVehicle);
  const selectedVehicleId = useMapStore((s) => s.selectedVehicleId);
  const vehicles = useTrafficStore((s) => s.vehicles);

  const prev = useRef(new Map<string, Frame>());
  const target = useRef(new Map<string, Frame>());
  const updatedAt = useRef(performance.now());
  const interval = useRef(1000);
  const raf = useRef<number>(0);
  const selectedRef = useRef(selectedVehicleId);
  selectedRef.current = selectedVehicleId;

  // --- one-time layer setup -------------------------------------------------
  useEffect(() => {
    for (const [type, name] of Object.entries(VEHICLE_ICON_ID) as [VehicleType, string][]) {
      try {
        upsertMapImage(map, name, makeVehicleIcon(type, VEHICLE_COLOR[type]));
      } catch (err) {
        console.warn("vehicle sprite failed", name, err);
      }
    }

    if (!map.getSource(SRC)) {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      map.addSource(SRC, { type: "geojson", data: empty });
    }

    if (!map.getLayer(RING)) {
      map.addLayer({
        id: RING,
        type: "circle",
        source: SRC,
        filter: ["==", ["get", "id"], "__none__"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 8, 17, 14],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": "#5fd0ff",
          "circle-stroke-width": 2,
        },
      });
    }

    if (!map.getLayer(ICON)) {
      // A tiny colour backplate keeps the fleet legible over light and dark
      // basemap tiles. The detailed silhouette is painted above it.
      // At city zoom a vehicle is a small, crisp dot: the road stays readable
      // and the fleet reads as flow. Silhouettes take over once you zoom in.
      map.addLayer({
        id: BACKPLATE,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 1.8, 14, 2.8, 16, 3.6, 18, 4],
          "circle-color": ["get", "color"],
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 15.6, 1, 16.4, 0],
          "circle-stroke-color": "rgba(255,255,255,0.9)",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 11, 0.6, 15, 1.2],
          "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], 15.6, 1, 16.4, 0],
        },
      });
      map.addLayer({
        id: ICON,
        type: "symbol",
        source: SRC,
        layout: {
          "icon-image": [
            "match",
            ["get", "vtype"],
            "car",
            VEHICLE_ICON_ID.car,
            "bus",
            VEHICLE_ICON_ID.bus,
            "truck",
            VEHICLE_ICON_ID.truck,
            "motorcycle",
            VEHICLE_ICON_ID.motorcycle,
            "ambulance",
            VEHICLE_ICON_ID.ambulance,
            VEHICLE_ICON_ID.car,
          ],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 15.5, 0.5, 17, 0.72, 19, 0.95],
          "icon-rotate": ["get", "heading"],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          "icon-anchor": "center",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "icon-padding": 0,
        },
        paint: {
          "icon-opacity": ["interpolate", ["linear"], ["zoom"], 15.6, 0, 16.4, 1],
        },
      });
    }

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
      if (!isMapAlive(map)) return;
      map.off("click", ICON, onClick);
      map.off("mouseenter", ICON, onEnter);
      map.off("mouseleave", ICON, onLeave);
      for (const id of [ICON, BACKPLATE, RING]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map, setSelectedVehicle]);

  useEffect(() => {
    if (!isMapAlive(map)) return;
    if (map.getLayer(RING)) {
      map.setFilter(RING, ["==", ["get", "id"], selectedVehicleId ?? "__none__"]);
    }
  }, [map, selectedVehicleId]);

  // --- visibility --------------------------------------------------------
  useEffect(() => {
    if (!isMapAlive(map)) return;
    const v = visible ? "visible" : "none";
    for (const id of [ICON, BACKPLATE, RING])
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

  // --- animation loop -------------------------------------------
  // Runs every frame only while there are vehicles to glide. With none, it
  // clears the layer once and then just checks back a few times a second, so
  // an empty map is not redrawn 60 times a second.
  useEffect(() => {
    let timer = 0;
    let showing = false;
    const tick = () => {
      if (!isMapAlive(map)) return;
      const src = map.getSource(SRC) as GeoJSONSource | undefined;
      if (target.current.size === 0) {
        if (showing) {
          src?.setData({ type: "FeatureCollection", features: [] });
          showing = false;
        }
        timer = window.setTimeout(() => {
          raf.current = requestAnimationFrame(tick);
        }, 250);
        return;
      }
      if (src) {
        showing = true;
        const reduced = prefersReducedMotion();
        const f = reduced
          ? 1
          : Math.min(1, (performance.now() - updatedAt.current) / interval.current);
        const selectedId = selectedRef.current;
        const features: Feature<Point>[] = [];
        for (const [id, t] of target.current) {
          const p = prev.current.get(id);
          const frame =
            p && !reduced
              ? {
                  lng: p.lng + (t.lng - p.lng) * f,
                  lat: p.lat + (t.lat - p.lat) * f,
                  heading: p.heading + angleDelta(p.heading, t.heading) * f,
                  type: t.type,
                  speed: t.speed,
                }
              : t;
          features.push(toFeature(id, frame, id === selectedId));
        }
        src.setData({ type: "FeatureCollection", features });
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf.current);
      window.clearTimeout(timer);
    };
  }, [map]);

  return null;
}
