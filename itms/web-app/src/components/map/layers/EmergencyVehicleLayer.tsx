import { useEffect, useMemo, useRef } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";
import type { Feature, FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { isMapAlive } from "@/components/map/mapSafe";
import { useEmergencyStore } from "@/store/emergencyStore";
import { buildVehicleFrames, type VehicleFrame } from "@/components/map/emergencyGeo";
import { VEHICLE_COLOR } from "@/components/map/mapColors";
import {
  AMBULANCE_BEACON_ICON_ID,
  EMERGENCY_ICON_ID,
  iconIdForEmergencyKind,
  makeEmergencyIcon,
  upsertMapImage,
} from "@/components/map/mapIcons";
import { angleDelta, bearingDeg } from "@/utils/geo";
import type { EmergencyVehicleKind } from "@/types";

const SRC = "em-vehicles";
const HALO = "em-vehicles-halo";
const ICON = "em-vehicles-icon";
const SELECTED_BOOST: ExpressionSpecification = ["case", [">", ["to-number", ["get", "selected"]], 0], 1.35, 1];

/**
 * Every active emergency vehicle, fed by the `emergency.vehicle-updated`
 * stream (`request.live`) — not just the selected mission's (`buildVehicleFrames`,
 * `emergencyGeo.ts`, is the pure, unit-tested logic for which ones and how).
 * Positions arrive ~1 Hz; this re-interpolates every animation frame so each
 * marker glides instead of teleporting, same approach as `VehicleLayer`. Each
 * vehicle keeps its mission's colour (shared with `EmergencyRouteLayer`) and a
 * bigger, brighter halo while its request is the selected one.
 */
export function EmergencyVehicleLayer({
  visible,
  onlyRequestId,
}: {
  visible: boolean;
  /** Draw just this request's vehicle (`null`: none). Left out, every active vehicle
   *  is drawn, which is what the operator console wants. A crew must see only
   *  its own vehicle; other crews' missions are not its business. */
  onlyRequestId?: string | null;
}) {
  const map = useMapInstance();
  const allRequests = useEmergencyStore((s) => s.requests);
  const requests = useMemo(
    () => (onlyRequestId === undefined ? allRequests : allRequests.filter((r) => r.id === onlyRequestId)),
    [allRequests, onlyRequestId],
  );
  const selectedRequestId = useEmergencyStore((s) => s.selectedRequestId);

  const prev = useRef(new Map<string, VehicleFrame>());
  const target = useRef(new Map<string, VehicleFrame>());
  const heading = useRef(new Map<string, number>());
  const updatedAt = useRef(performance.now());
  const interval = useRef(1000);
  const raf = useRef(0);

  useEffect(() => {
    for (const [kind, name] of Object.entries(EMERGENCY_ICON_ID) as [
      EmergencyVehicleKind,
      string,
    ][]) {
      const color =
        kind === "ambulance" ? VEHICLE_COLOR.ambulance : kind === "fire_truck" ? "#ff8a4c" : "#6ea8ff";
      try {
        upsertMapImage(map, name, makeEmergencyIcon(kind, color));
      } catch (err) {
        console.warn("emergency sprite failed", name, err);
      }
    }
    // Symbol images are GPU textures. Register both quiet beacon phases once,
    // then select the texture from feature data during the existing frame loop.
    try {
      upsertMapImage(
        map,
        AMBULANCE_BEACON_ICON_ID.red,
        makeEmergencyIcon("ambulance", VEHICLE_COLOR.ambulance, 80, true),
      );
      upsertMapImage(
        map,
        AMBULANCE_BEACON_ICON_ID.blue,
        makeEmergencyIcon("ambulance", VEHICLE_COLOR.ambulance, 80, false),
      );
    } catch (err) {
      console.warn("ambulance beacon sprite failed", err);
    }

    if (!map.getSource(SRC)) {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      map.addSource(SRC, { type: "geojson", data: empty });
    }
    if (!map.getLayer(HALO)) {
      map.addLayer({
        id: HALO,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 9, 17, 18],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.22,
          "circle-blur": 0.35,
        },
      });
    }
    if (!map.getLayer(ICON)) {
      map.addLayer({
        id: ICON,
        type: "symbol",
        source: SRC,
        layout: {
          "icon-image": [
            "case",
            ["==", ["get", "kind"], "ambulance"],
            [
              "case",
              [">", ["to-number", ["get", "beaconRed"]], 0],
              AMBULANCE_BEACON_ICON_ID.red,
              AMBULANCE_BEACON_ICON_ID.blue,
            ],
            [
              "match",
              ["get", "kind"],
              "fire_truck",
              EMERGENCY_ICON_ID.fire_truck,
              "police",
              EMERGENCY_ICON_ID.police,
              EMERGENCY_ICON_ID.ambulance,
            ],
          ],
          // A zoom curve must be the top-level expression, so the selected
          // boost multiplies inside each stop rather than around the curve.
          "icon-size": [
            "interpolate",
            ["linear"],
            ["zoom"],
            11, ["*", 0.62, SELECTED_BOOST],
            13, ["*", 0.85, SELECTED_BOOST],
            16, ["*", 1.12, SELECTED_BOOST],
            18, ["*", 1.32, SELECTED_BOOST],
          ],
          "icon-rotate": ["to-number", ["get", "heading"]],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          "icon-anchor": "center",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "icon-padding": 0,
        },
      });
    }

    const start = performance.now();
    const loop = () => {
      if (!isMapAlive(map)) return;
      const src = map.getSource(SRC) as GeoJSONSource | undefined;
      if (src) {
        const reduced = prefersReducedMotion();
        // A restrained red/blue alternation: once per 1.2 s, not a strobe.
        // Reduced-motion users receive the stable red phase.
        const beaconRed = reduced || ((performance.now() - start) % 1200) < 600;
        const f = reduced
          ? 1
          : Math.min(1, (performance.now() - updatedAt.current) / interval.current);
        const features: Feature<Point>[] = [];
        for (const [id, t] of target.current) {
          const p = prev.current.get(id) ?? t;
          const lng = p.lng + (t.lng - p.lng) * f;
          const lat = p.lat + (t.lat - p.lat) * f;
          const moved = Math.hypot(t.lng - p.lng, t.lat - p.lat) > 1e-7;
          const targetHeading = moved
            ? bearingDeg([p.lng, p.lat], [t.lng, t.lat])
            : (heading.current.get(id) ?? 0);
          const fromHeading = heading.current.get(id) ?? targetHeading;
          const hdg = fromHeading + angleDelta(fromHeading, targetHeading) * (reduced ? 1 : f);
          heading.current.set(id, hdg);
          features.push({
            type: "Feature",
            id,
            properties: {
              id,
              kind: t.kind,
              icon: iconIdForEmergencyKind(t.kind),
              progress: t.progress,
              color: t.color,
              selected: t.selected ? 1 : 0,
              heading: hdg,
              beaconRed: beaconRed ? 1 : 0,
            },
            geometry: {
              type: "Point",
              coordinates: [lng, lat],
            },
          });
        }
        src.setData({ type: "FeatureCollection", features });
        if (map.getLayer(HALO)) {
          const phase = reduced ? 0.35 : ((performance.now() - start) % 1600) / 1600;
          map.setPaintProperty(HALO, "circle-radius", [
            "interpolate",
            ["linear"],
            ["zoom"],
            12,
            ["case", [">", ["get", "selected"], 0], 10 + phase * 8, 7 + phase * 4],
            17,
            ["case", [">", ["get", "selected"], 0], 20 + phase * 10, 14 + phase * 6],
          ]);
          if (!reduced) {
            const beaconColor = beaconRed ? "rgba(255, 60, 70, 0.85)" : "rgba(70, 110, 255, 0.85)";
            map.setPaintProperty(HALO, "circle-color", [
              "case",
              [">", ["get", "selected"], 0],
              beaconColor,
              ["get", "color"],
            ]);
          } else {
            map.setPaintProperty(HALO, "circle-color", ["get", "color"]);
          }
          map.setPaintProperty(HALO, "circle-opacity", [
            "case",
            [">", ["get", "selected"], 0],
            reduced ? 0.28 : 0.32 * (1 - phase * 0.45),
            0.16,
          ]);
        }
      }
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf.current);
      if (!isMapAlive(map)) return;
      for (const id of [ICON, HALO]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map]);

  useEffect(() => {
    if (!isMapAlive(map)) return;
    const v = visible ? "visible" : "none";
    for (const id of [ICON, HALO])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  useEffect(() => {
    const now = performance.now();
    interval.current = Math.min(2500, Math.max(250, now - updatedAt.current));
    updatedAt.current = now;
    prev.current = new Map(target.current);
    const shown =
      onlyRequestId === undefined ? requests : requests.filter((r) => r.id === onlyRequestId);
    target.current = buildVehicleFrames(shown, selectedRequestId);
  }, [requests, selectedRequestId, onlyRequestId]);

  return null;
}
