import { useEffect, useRef } from "react";
import type { GeoJSONSource } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useEmergencyStore } from "@/store/emergencyStore";
import {
  buildCorridorFeatures,
  buildPointFeatures,
  buildRouteFeatures,
  buildSegmentFeatures,
  isDriving,
  type CutPoint,
} from "@/components/map/emergencyGeo";
import {
  ANOMALY_SEVERITY_COLOR,
  EV_ROUTE_ALT_CASING,
  EV_ROUTE_ALT_COLOR,
  EV_ROUTE_CASING,
} from "@/components/map/mapColors";

const ROUTE_SRC = "em-route";
const PT_SRC = "em-route-pts";
const CORRIDOR_SRC = "em-corridor";
const SEG_SRC = "em-route-segs";
const ROUTE_GLOW = "em-route-glow";
const ROUTE_LINE = "em-route-line";
const ROUTE_ALT = "em-route-alt";
const ROUTE_ALT_CASING = "em-route-alt-casing";
const ROUTE_CASING = "em-route-casing";
const SEG_CONGEST = "em-route-congest";
const SEG_AVOID = "em-route-avoid";
const PT_RING = "em-route-pt-ring";
const PT_ICON = "em-route-pt-icon";
const CORRIDOR_RING = "em-corridor-ring";
const CORRIDOR_DOT = "em-corridor-dot";

const CONGEST = "#f5b83d";
// an anomalous road the route steered around: anomaly colour, hollow ring
const AVOID = ANOMALY_SEVERITY_COLOR.high;

/**
 * Every active emergency request's route(s), vehicle-independent map state:
 * the recommended route for each mission (dimmed unless selected), the
 * selected mission's alternatives + congested/avoided-segment call-outs
 * (preview detail scoped to the one request being inspected), source/
 * destination markers, and every active mission's green-corridor reservations.
 * A mission keeps its own colour (`colorForRequest`) for its whole lifetime,
 * so it stays traceable across the map, the panel and its vehicle marker.
 *
 * All the actual feature-building is in `emergencyGeo.ts` (pure, unit-tested);
 * this component is just the imperative MapLibre wiring around it. Renders
 * every non-terminal request simultaneously — selecting a different request
 * changes which one is emphasised, it never hides the others.
 */
export function EmergencyRouteLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const requests = useEmergencyStore((s) => s.requests);
  const selectedRequestId = useEmergencyStore((s) => s.selectedRequestId);
  const previewRank = useEmergencyStore((s) => s.previewRank);
  const draft = useEmergencyStore((s) => s.draft);
  // Per driving request, its last two distinct reported positions. The
  // marker glides from the older one to the newer one between reports, so
  // cutting the route at the older one keeps the line starting under the
  // marker instead of running ahead of it.
  const positions = useRef(new Map<string, { last: CutPoint; before?: CutPoint }>());

  useEffect(() => {
    if (!map.getSource(ROUTE_SRC)) {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      map.addSource(ROUTE_SRC, { type: "geojson", data: empty });
      map.addSource(PT_SRC, { type: "geojson", data: empty });
      map.addSource(CORRIDOR_SRC, { type: "geojson", data: empty });
      map.addSource(SEG_SRC, { type: "geojson", data: empty });

      map.addLayer({
        id: CORRIDOR_RING,
        type: "circle",
        source: CORRIDOR_SRC,
        paint: {
          // A `case` can't wrap two independent `interpolate`s (MapLibre:
          // "only one zoom-based interpolate subexpression may be used") --
          // `interpolate` has to be the outer expression, with `case` only
          // choosing the value *at* each zoom stop.
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            12, ["case", ["get", "selected"], 11, 8],
            17, ["case", ["get", "selected"], 24, 17],
          ],
          "circle-color": ["get", "color"],
          "circle-opacity": [
            "case", ["get", "held"],
            ["case", ["get", "selected"], 0.2, 0.1], ["case", ["get", "selected"], 0.07, 0.04],
          ],
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": ["case", ["get", "held"], ["case", ["get", "selected"], 2.5, 1.5], 1],
          "circle-stroke-opacity": ["case", ["get", "held"], ["case", ["get", "selected"], 0.95, 0.6], 0.35],
        },
      });
      map.addLayer({
        id: CORRIDOR_DOT,
        type: "circle",
        source: CORRIDOR_SRC,
        paint: {
          "circle-radius": 3,
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["get", "held"], 1, 0.5],
        },
      });

      // alternatives of the selected request only — preview detail, not a
      // mission. Solid and outlined like the main route, but lighter and
      // thinner, so they are clearly "other ways" and drawn beneath it.
      map.addLayer({
        id: ROUTE_ALT_CASING,
        type: "line",
        source: ROUTE_SRC,
        filter: ["==", ["get", "kind"], "alt"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": EV_ROUTE_ALT_CASING,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 4, 17, 9],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: ROUTE_ALT,
        type: "line",
        source: ROUTE_SRC,
        filter: ["==", ["get", "kind"], "alt"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": EV_ROUTE_ALT_COLOR,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 17, 6],
          "line-opacity": 1,
        },
      });
      // every active mission's main route — bright + glowing when selected,
      // dimmer (but still its own colour) otherwise
      map.addLayer({
        id: ROUTE_GLOW,
        type: "line",
        source: ROUTE_SRC,
        filter: ["all", ["==", ["get", "kind"], "main"], ["get", "selected"]],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 8, 17, 20],
          "line-opacity": 0.18,
          "line-blur": 3,
        },
      });
      // dark outline under every main route: separates it from whatever
      // congestion colour the road beneath it carries
      map.addLayer({
        id: ROUTE_CASING,
        type: "line",
        source: ROUTE_SRC,
        filter: ["==", ["get", "kind"], "main"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": EV_ROUTE_CASING,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            12, ["case", ["get", "selected"], 5.5, 3.5],
            17, ["case", ["get", "selected"], 12, 7],
          ],
          "line-opacity": ["case", ["get", "selected"], 1, 0.85],
        },
      });
      map.addLayer({
        id: ROUTE_LINE,
        type: "line",
        source: ROUTE_SRC,
        filter: ["==", ["get", "kind"], "main"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            12, ["case", ["get", "selected"], 3.5, 2],
            17, ["case", ["get", "selected"], 8, 4.5],
          ],
          "line-opacity": ["case", ["get", "selected"], 1, 0.85],
        },
      });
      // congested segments on the previewed route
      map.addLayer({
        id: SEG_CONGEST,
        type: "line",
        source: SEG_SRC,
        filter: ["==", ["get", "kind"], "congest"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": CONGEST,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 3.5, 17, 8],
          "line-opacity": 0.9,
          "line-dasharray": [1.5, 1],
        },
      });
      // steered-around anomalous segments (off-route)
      map.addLayer({
        id: SEG_AVOID,
        type: "circle",
        source: SEG_SRC,
        filter: ["==", ["get", "kind"], "avoid"],
        paint: {
          "circle-radius": 5,
          "circle-color": "transparent",
          "circle-stroke-color": AVOID,
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": 0.85,
        },
      });

      map.addLayer({
        id: PT_RING,
        type: "circle",
        source: PT_SRC,
        paint: {
          "circle-radius": 9,
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["get", "selected"], 0.2, 0.12],
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": ["case", ["get", "selected"], 1.5, 1],
          "circle-stroke-opacity": ["case", ["get", "selected"], 1, 0.5],
        },
      });
      map.addLayer({
        id: PT_ICON,
        type: "circle",
        source: PT_SRC,
        paint: {
          "circle-radius": ["case", ["get", "selected"], 4.5, 3.5],
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["get", "selected"], 1, 0.6],
          "circle-stroke-color": "#0a0e14",
          "circle-stroke-width": 1.5,
        },
      });
    }
    return () => {
      for (const id of [
        CORRIDOR_DOT, CORRIDOR_RING, SEG_AVOID, SEG_CONGEST,
        PT_ICON, PT_RING, ROUTE_LINE, ROUTE_CASING, ROUTE_GLOW, ROUTE_ALT, ROUTE_ALT_CASING,
      ]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      for (const id of [ROUTE_SRC, PT_SRC, CORRIDOR_SRC, SEG_SRC]) {
        if (map.getSource(id)) map.removeSource(id);
      }
    };
  }, [map]);

  useEffect(() => {
    const v = visible ? "visible" : "none";
    for (const id of [
      CORRIDOR_DOT, CORRIDOR_RING, SEG_AVOID, SEG_CONGEST,
      PT_ICON, PT_RING, ROUTE_LINE, ROUTE_CASING, ROUTE_GLOW, ROUTE_ALT, ROUTE_ALT_CASING,
    ]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
    }
  }, [map, visible]);

  useEffect(() => {
    const routeSrc = map.getSource(ROUTE_SRC) as GeoJSONSource | undefined;
    const ptSrc = map.getSource(PT_SRC) as GeoJSONSource | undefined;
    const corridorSrc = map.getSource(CORRIDOR_SRC) as GeoJSONSource | undefined;
    const segSrc = map.getSource(SEG_SRC) as GeoJSONSource | undefined;
    if (!routeSrc || !ptSrc || !corridorSrc || !segSrc) return;

    const cutAt = new Map<string, CutPoint>();
    const seen = new Set<string>();
    for (const r of requests) {
      const live = r.live;
      if (!isDriving(r) || !live || live.lat == null || live.lon == null) continue;
      seen.add(r.id);
      const now: CutPoint = { lng: live.lon, lat: live.lat, edgeId: live.edgeId, progress: live.routeProgress };
      const known = positions.current.get(r.id);
      if (!known) positions.current.set(r.id, { last: now });
      else if (known.last.lng !== now.lng || known.last.lat !== now.lat) {
        positions.current.set(r.id, { last: now, before: known.last });
      }
      const p = positions.current.get(r.id)!;
      cutAt.set(r.id, p.before ?? p.last);
    }
    for (const id of positions.current.keys()) if (!seen.has(id)) positions.current.delete(id);

    routeSrc.setData({
      type: "FeatureCollection",
      features: buildRouteFeatures(requests, selectedRequestId, previewRank, cutAt),
    });
    segSrc.setData({
      type: "FeatureCollection",
      features: buildSegmentFeatures(requests, selectedRequestId, previewRank),
    });
    ptSrc.setData({
      type: "FeatureCollection",
      features: buildPointFeatures(requests, selectedRequestId, draft),
    });
    corridorSrc.setData({
      type: "FeatureCollection",
      features: buildCorridorFeatures(requests, selectedRequestId),
    });
  }, [map, requests, selectedRequestId, previewRank, draft]);

  return null;
}
