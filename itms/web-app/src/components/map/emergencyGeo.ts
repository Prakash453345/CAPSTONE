/**
 * Pure GeoJSON/feature-building for the emergency map layers — kept separate
 * from `EmergencyRouteLayer` / `EmergencyVehicleLayer` (which are thin
 * imperative MapLibre wrappers around these) so the actual multi-request
 * rendering logic is unit-testable without a map instance.
 *
 * The contract this enforces: every non-terminal `EmergencyRequest` renders
 * something (route, points, corridor, vehicle) regardless of which one is
 * selected; only the selected request's alternatives / congested-segment
 * detail are drawn, and only the selected request's marker is emphasised.
 */
import type { Feature, LineString, Point } from "geojson";
import { edgeById, junctionById } from "@/data/network";
import { colorForRequest } from "@/components/map/emergencyColors";
import { CORRIDOR_ACCENT_COLOR, EV_ROUTE_COLOR } from "@/components/map/mapColors";
import {
  isTerminalRequest,
  requestRoutes,
  type DispatchDraft,
} from "@/store/emergencyStore";
import type { EmergencyRequest } from "@/types";

/** [lng,lat] polyline for a list of route edge ids, gaps skipped. */
export function edgesToCoords(edges: readonly string[]): number[][] {
  const out: number[][] = [];
  for (const eid of edges) {
    const e = edgeById.get(eid);
    if (e) out.push(...e.path);
  }
  return out;
}

/** Midpoint of a named edge, or null if the edge isn't in the bundled network. */
export function edgeMidpoint(edgeId: string | undefined): [number, number] | null {
  if (!edgeId) return null;
  const e = edgeById.get(edgeId);
  if (!e) return null;
  const mid = e.path[Math.floor(e.path.length / 2)];
  return [mid[0], mid[1]];
}

export interface RouteFeatureProps {
  requestId: string;
  kind: "main" | "alt";
  selected: boolean;
  color: string;
}

/**
 * One line feature per route actually drawn: every active request's
 * recommended route (as `"main"`), plus — for the selected request only —
 * every other route it offers (as `"alt"`), with whichever one the operator
 * is previewing promoted to `"main"` for that request.
 */
export function buildRouteFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
  previewRank: number,
): Feature<LineString, RouteFeatureProps>[] {
  const out: Feature<LineString, RouteFeatureProps>[] = [];
  for (const req of requests) {
    if (isTerminalRequest(req)) continue;
    const selected = req.id === selectedRequestId;
    const color = EV_ROUTE_COLOR;
    const routes = selected ? requestRoutes(req) : req.route ? [req.route] : [];
    const mainIdx = selected ? (routes[previewRank] ? previewRank : 0) : 0;
    routes.forEach((rt, i) => {
      const coords = edgesToCoords(rt.edges);
      if (coords.length < 2) return;
      out.push({
        type: "Feature",
        properties: { requestId: req.id, kind: i === mainIdx ? "main" : "alt", selected, color },
        geometry: { type: "LineString", coordinates: coords },
      });
    });
  }
  return out;
}

export interface SegmentFeatureProps {
  requestId: string;
  kind: "congest" | "avoid";
}

/** Congested / anomaly-avoided call-outs for the selected request's previewed
 *  route only — explanatory detail tied to the open route panel. */
export function buildSegmentFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
  previewRank: number,
): Feature<LineString | Point, SegmentFeatureProps>[] {
  const req = requests.find((r) => r.id === selectedRequestId);
  if (!req || isTerminalRequest(req)) return [];
  const routes = requestRoutes(req);
  const previewed = routes[previewRank] ?? routes[0];
  if (!previewed) return [];

  const out: Feature<LineString | Point, SegmentFeatureProps>[] = [];
  for (const eid of previewed.congestedSegments) {
    const e = edgeById.get(eid);
    if (e && e.path.length >= 2) {
      out.push({
        type: "Feature",
        properties: { requestId: req.id, kind: "congest" },
        geometry: { type: "LineString", coordinates: e.path },
      });
    }
  }
  for (const eid of previewed.anomalousSegmentsAvoided) {
    const mid = edgeMidpoint(eid);
    if (mid) {
      out.push({
        type: "Feature",
        properties: { requestId: req.id, kind: "avoid" },
        geometry: { type: "Point", coordinates: mid },
      });
    }
  }
  return out;
}

export interface PointFeatureProps {
  requestId: string | null;
  color: string;
  selected: boolean;
}

const SOURCE_COLOR = "#46c46a";
const DEST_COLOR = "#e5484d";

/** Source/destination markers for every active request, plus the operator's
 *  in-progress draft (always drawn at full prominence). */
export function buildPointFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
  draft: DispatchDraft | null,
): Feature<Point, PointFeatureProps>[] {
  const out: Feature<Point, PointFeatureProps>[] = [];
  for (const req of requests) {
    if (isTerminalRequest(req)) continue;
    const selected = req.id === selectedRequestId;
    const src = edgeMidpoint(req.sourceEdge);
    const dst = edgeMidpoint(req.destinationEdge);
    if (src) out.push(pointFeature(req.id, src, SOURCE_COLOR, selected));
    if (dst) out.push(pointFeature(req.id, dst, DEST_COLOR, selected));
  }
  if (draft?.source) out.push(pointFeature(null, draft.source.at, SOURCE_COLOR, true));
  if (draft?.destination) out.push(pointFeature(null, draft.destination.at, DEST_COLOR, true));
  return out;
}

function pointFeature(
  requestId: string | null,
  at: [number, number],
  color: string,
  selected: boolean,
): Feature<Point, PointFeatureProps> {
  return {
    type: "Feature",
    properties: { requestId, color, selected },
    geometry: { type: "Point", coordinates: at },
  };
}

export interface CorridorFeatureProps {
  requestId: string;
  color: string;
  held: boolean;
  selected: boolean;
}

/** Green-corridor reservation rings for every active request that has one —
 *  not just the selected mission. */
export function buildCorridorFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
): Feature<Point, CorridorFeatureProps>[] {
  const out: Feature<Point, CorridorFeatureProps>[] = [];
  for (const req of requests) {
    if (isTerminalRequest(req) || !req.corridor) continue;
    const selected = req.id === selectedRequestId;
    const color = CORRIDOR_ACCENT_COLOR;
    const passed = new Set(req.corridor.passedIntersections);
    for (const r of req.corridor.reservations) {
      const j = junctionById.get(r.intersectionId);
      if (!j) continue;
      out.push({
        type: "Feature",
        properties: { requestId: req.id, color, held: !passed.has(r.intersectionId), selected },
        geometry: { type: "Point", coordinates: [j.lng, j.lat] },
      });
    }
  }
  return out;
}

export interface VehicleFrame {
  lng: number;
  lat: number;
  progress: number;
  kind: string;
  color: string;
  selected: boolean;
}

/** One live-position frame per active request with a vehicle position —
 *  every in-progress mission's vehicle, each carrying its own mission colour
 *  and whether its request is the selected one. */
export function buildVehicleFrames(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
): Map<string, VehicleFrame> {
  const out = new Map<string, VehicleFrame>();
  for (const req of requests) {
    const live = req.live;
    if (!live || live.lat == null || live.lon == null || isTerminalRequest(req)) continue;
    out.set(req.id, {
      lng: live.lon,
      lat: live.lat,
      progress: live.routeProgress,
      kind: req.vehicleKind,
      color: colorForRequest(req.id),
      selected: req.id === selectedRequestId,
    });
  }
  return out;
}
