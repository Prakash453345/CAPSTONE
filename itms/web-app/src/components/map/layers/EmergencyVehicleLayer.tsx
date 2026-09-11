import { useEffect, useRef } from "react";
import type { GeoJSONSource } from "maplibre-gl";
import type { Feature, FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useEmergencyStore } from "@/store/emergencyStore";
import { buildVehicleFrames, type VehicleFrame } from "@/components/map/emergencyGeo";

const SRC = "em-vehicles";
const HALO = "em-vehicles-halo";
const DOT = "em-vehicles-dot";

/**
 * Every active emergency vehicle, fed by the `emergency.vehicle-updated`
 * stream (`request.live`) — not just the selected mission's (`buildVehicleFrames`,
 * `emergencyGeo.ts`, is the pure, unit-tested logic for which ones and how).
 * Positions arrive ~1 Hz; this re-interpolates every animation frame so each
 * marker glides instead of teleporting, same approach as `VehicleLayer`. Each
 * vehicle keeps its mission's colour (shared with `EmergencyRouteLayer`) and a
 * bigger, brighter halo while its request is the selected one.
 */
export function EmergencyVehicleLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const requests = useEmergencyStore((s) => s.requests);
  const selectedRequestId = useEmergencyStore((s) => s.selectedRequestId);

  const prev = useRef(new Map<string, VehicleFrame>());
  const target = useRef(new Map<string, VehicleFrame>());
  const updatedAt = useRef(performance.now());
  const interval = useRef(1000);
  const raf = useRef(0);

  useEffect(() => {
    if (!map.getSource(SRC)) {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      map.addSource(SRC, { type: "geojson", data: empty });
      map.addLayer({
        id: HALO,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 9, 17, 18],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.22,
        },
      });
      map.addLayer({
        id: DOT,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": [
            "case", ["get", "selected"],
            ["interpolate", ["linear"], ["zoom"], 12, 4.5, 17, 8],
            ["interpolate", ["linear"], ["zoom"], 12, 3, 17, 5.5],
          ],
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["get", "selected"], 1, 0.65],
          "circle-stroke-color": "#0a0e14",
          "circle-stroke-width": 2,
        },
      });
    }

    const start = performance.now();
    const loop = () => {
      const src = map.getSource(SRC) as GeoJSONSource | undefined;
      if (src) {
        const f = Math.min(1, (performance.now() - updatedAt.current) / interval.current);
        const features: Feature<Point>[] = [];
        for (const [id, t] of target.current) {
          const p = prev.current.get(id) ?? t;
          features.push({
            type: "Feature",
            id,
            properties: { id, kind: t.kind, progress: t.progress, color: t.color, selected: t.selected },
            geometry: {
              type: "Point",
              coordinates: [p.lng + (t.lng - p.lng) * f, p.lat + (t.lat - p.lat) * f],
            },
          });
        }
        src.setData({ type: "FeatureCollection", features });
        // gentle halo breathing, bigger for the selected mission's vehicle
        if (map.getLayer(HALO)) {
          const phase = ((performance.now() - start) % 1400) / 1400;
          map.setPaintProperty(HALO, "circle-radius", [
            "case", ["get", "selected"],
            ["interpolate", ["linear"], ["zoom"], 12, 8 + phase * 20, 17, 16 + phase * 26],
            ["interpolate", ["linear"], ["zoom"], 12, 7 + phase * 10, 17, 13 + phase * 14],
          ]);
          map.setPaintProperty(HALO, "circle-opacity", [
            "case", ["get", "selected"], 0.3 * (1 - phase), 0.14 * (1 - phase),
          ]);
        }
      }
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf.current);
      for (const id of [DOT, HALO]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map]);

  useEffect(() => {
    const v = visible ? "visible" : "none";
    for (const id of [DOT, HALO])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  useEffect(() => {
    const now = performance.now();
    interval.current = Math.min(2500, Math.max(250, now - updatedAt.current));
    updatedAt.current = now;
    prev.current = new Map(target.current);
    target.current = buildVehicleFrames(requests, selectedRequestId);
  }, [requests, selectedRequestId]);

  return null;
}
