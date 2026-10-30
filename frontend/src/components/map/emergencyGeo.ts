/**
 * Pure GeoJSON/feature-building for the emergency map layers — kept separate
 * from `EmergencyRouteLayer` / `EmergencyVehicleLayer` (which are thin
 * imperative MapLibre wrappers around these) so the actual multi-request
 * rendering logic is unit-testable without a map instance.
 *
 * The contract this enforces, modelled on a navigation app: the map shows the
 * trip you are looking at and the vehicles actually on the road, nothing else.
 *
 * - The selected request: its route(s). While it is still being planned, its
 *   alternatives too (the operator is choosing); once its vehicle is driving,
 *   only the road ahead of the vehicle.
 * - Any other request whose vehicle is driving: only the road ahead, dimmed.
 * - A planned request that is not selected: nothing on the map (it is listed
 *   in the panel). Leaving every past plan drawn is what cluttered the map.
 * - The part of a route the vehicle has already driven is never drawn.
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

/** A request whose vehicle is out on the road (dispatched, not yet arrived). */
export function isDriving(req: Pick<EmergencyRequest, "state">): boolean {
  return req.state === "in_transit" || req.state === "green_corridor_active";
}

/** Where to start drawing a driving vehicle's route: a reported position,
 *  with the road it was on and its progress as a fraction of the route, used
 *  to pick the right stretch when two parts of a route run close together
 *  (the two carriageways of a road after a U-turn). */
export interface CutPoint {
  lng: number;
  lat: number;
  edgeId?: string;
  progress?: number;
}

/** The part of a route from `cut` onward: the polyline starts at `cut`
 *  projected onto the route, then follows the route to its end. */
export function trimRoute(edges: readonly string[], cut: CutPoint): number[][] {
  const coords: number[][] = [];
  const edgeOf: number[] = []; // index into `edges` for each coordinate
  edges.forEach((eid, i) => {
    const e = edgeById.get(eid);
    if (!e) return;
    for (const c of e.path) {
      coords.push(c);
      edgeOf.push(i);
    }
  });
  if (coords.length < 2) return coords;

  // local metric frame around the cut (equirectangular: exact enough over a
  // few kilometres, and only used to compare distances)
  const kx = 111_320 * Math.cos((cut.lat * Math.PI) / 180);
  const ky = 110_540;
  const xy = (c: number[]) => [(c[0] - cut.lng) * kx, (c[1] - cut.lat) * ky];

  const segLen: number[] = [];
  let total = 0;
  for (let i = 1; i < coords.length; i++) {
    const [ax, ay] = xy(coords[i - 1]);
    const [bx, by] = xy(coords[i]);
    const l = Math.hypot(bx - ax, by - ay);
    segLen.push(l);
    total += l;
  }

  // which segments may hold the vehicle: those on its road when that road is
  // on the route, else those near its progress along the route
  const onRoute = cut.edgeId ? edges.indexOf(cut.edgeId) : -1;
  const allowed = (i: number, along: number): boolean => {
    if (onRoute >= 0) return edgeOf[i - 1] === onRoute && edgeOf[i] === onRoute;
    if (cut.progress == null || total === 0) return true;
    return Math.abs(along / total - cut.progress) <= 0.08;
  };

  let best = { d: Infinity, seg: 1, t: 0 };
  const search = (restrict: boolean) => {
    let along = 0;
    for (let i = 1; i < coords.length; i++) {
      if (!restrict || allowed(i, along)) {
        const [ax, ay] = xy(coords[i - 1]);
        const [bx, by] = xy(coords[i]);
        const dx = bx - ax;
        const dy = by - ay;
        const den = dx * dx + dy * dy;
        const t = den === 0 ? 0 : Math.max(0, Math.min(1, (-ax * dx - ay * dy) / den));
        const d = Math.hypot(ax + t * dx, ay + t * dy);
        if (d < best.d) best = { d, seg: i, t };
      }
      along += segLen[i - 1];
    }
  };
  search(true);
  if (!Number.isFinite(best.d)) search(false); // nothing allowed: nearest point on the route

  const a = coords[best.seg - 1];
  const b = coords[best.seg];
  const start = [a[0] + (b[0] - a[0]) * best.t, a[1] + (b[1] - a[1]) * best.t];
  return [start, ...coords.slice(best.seg)];
}

export interface RouteFeatureProps {
  requestId: string;
  kind: "main" | "alt";
  selected: boolean;
  color: string;
}

/**
 * One line feature per route actually drawn (see the module contract): the
 * selected request's routes while it is being planned, with whichever one the
 * operator is previewing as `"main"` and the rest as `"alt"`; and, for every
 * request whose vehicle is driving, its route from `cutAt` (the vehicle's
 * position) onward.
 */
export function buildRouteFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
  previewRank: number,
  cutAt?: ReadonlyMap<string, CutPoint>,
): Feature<LineString, RouteFeatureProps>[] {
  const out: Feature<LineString, RouteFeatureProps>[] = [];
  const color = EV_ROUTE_COLOR;
  for (const req of requests) {
    if (isTerminalRequest(req)) continue;
    const selected = req.id === selectedRequestId;
    if (isDriving(req)) {
      if (!req.route) continue;
      const cut = cutAt?.get(req.id);
      const coords = cut ? trimRoute(req.route.edges, cut) : edgesToCoords(req.route.edges);
      if (coords.length < 2) continue;
      out.push({
        type: "Feature",
        properties: { requestId: req.id, kind: "main", selected, color },
        geometry: { type: "LineString", coordinates: coords },
      });
      continue;
    }
    if (!selected) continue;
    const routes = requestRoutes(req);
    const mainIdx = routes[previewRank] ? previewRank : 0;
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
  const driving = isDriving(req);
  const previewed = driving ? req.route : (routes[previewRank] ?? routes[0]);
  if (!previewed) return [];
  // once the vehicle is driving, only call out what is still ahead of it
  const at = driving && req.live?.edgeId ? previewed.edges.indexOf(req.live.edgeId) : -1;
  const ahead = new Set(at >= 0 ? previewed.edges.slice(at) : previewed.edges);

  const out: Feature<LineString | Point, SegmentFeatureProps>[] = [];
  for (const eid of previewed.congestedSegments) {
    if (!ahead.has(eid)) continue;
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

// Start in the route colour (green would read as free-flowing traffic), end in red.
const SOURCE_COLOR = EV_ROUTE_COLOR;
const DEST_COLOR = "#e5484d";

/** Start/destination markers: both for the selected request while it is
 *  being planned, the destination only for any request whose vehicle is
 *  driving (its start is behind it), plus the operator's in-progress draft
 *  (always drawn at full prominence). */
export function buildPointFeatures(
  requests: EmergencyRequest[],
  selectedRequestId: string | null,
  draft: DispatchDraft | null,
): Feature<Point, PointFeatureProps>[] {
  const out: Feature<Point, PointFeatureProps>[] = [];
  for (const req of requests) {
    if (isTerminalRequest(req)) continue;
    const selected = req.id === selectedRequestId;
    const driving = isDriving(req);
    if (!driving && !selected) continue;
    const src = driving ? null : edgeMidpoint(req.sourceEdge);
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
  /** Road the vehicle is on, when known. */
  lane?: string;
  /** Road-following route from the previous snapshot (set by the layer). */
  path?: [number, number][];
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
      lane: live.edgeId,
      progress: live.routeProgress,
      kind: req.vehicleKind,
      color: colorForRequest(req.id),
      selected: req.id === selectedRequestId,
    });
  }
  return out;
}
