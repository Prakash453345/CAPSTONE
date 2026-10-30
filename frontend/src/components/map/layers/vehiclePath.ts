import { edgeById } from "@/data/network";
import { cumulativeLengths, haversineMeters, pointAlongPath, type LngLat } from "@/utils/geo";

/** A vehicle observation as far as path-following needs it. */
export interface Fix {
  lng: number;
  lat: number;
  /** Road the vehicle is on (SUMO edge id). Junction-internal ids start with ":". */
  lane?: string;
}

/** Farther than this from its road, a fix is not trusted to be on it. */
const MAX_SNAP_M = 25;
/** The end of one road and the start of the next must meet within this to be joined. */
const MAX_JOIN_M = 40;

const MPD_LAT = 111_320;

/** Distance along `path` (m) of the point nearest `p`, and how far `p` is from the road. */
function project(path: LngLat[], cum: number[], p: LngLat): { s: number; off: number } {
  const kx = MPD_LAT * Math.cos((p[1] * Math.PI) / 180);
  let best = { s: 0, off: Infinity };
  for (let i = 1; i < path.length; i++) {
    const ax = (path[i - 1][0] - p[0]) * kx;
    const ay = (path[i - 1][1] - p[1]) * MPD_LAT;
    const bx = (path[i][0] - p[0]) * kx;
    const by = (path[i][1] - p[1]) * MPD_LAT;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
    const off = Math.hypot(ax + dx * t, ay + dy * t);
    if (off < best.off) best = { s: cum[i - 1] + (cum[i] - cum[i - 1]) * t, off };
  }
  return best;
}

/** The part of an edge between two distances along it, as points. */
function slice(path: LngLat[], cum: number[], s1: number, s2: number): LngLat[] {
  const at = (s: number): LngLat => {
    const q = pointAlongPath(path, cum, s);
    return [q.lng, q.lat];
  };
  const pts: LngLat[] = [at(s1)];
  for (let i = 1; i < path.length - 1; i++) if (cum[i] > s1 && cum[i] < s2) pts.push(path[i]);
  pts.push(at(s2));
  return pts;
}

export function edgeOf(lane?: string): string | null {
  if (!lane || lane.startsWith(":")) return null;
  return lane;
}

/**
 * The route a vehicle most likely took between two snapshots: along its road
 * (and onto the next one) instead of the straight chord, which cuts across the
 * corner of every turn and can put the marker inside a city block.
 */
export function pathBetween(from: Fix, to: Fix): LngLat[] {
  const straight: LngLat[] = [
    [from.lng, from.lat],
    [to.lng, to.lat],
  ];
  const ea = edgeById.get(edgeOf(from.lane) ?? "");
  const eb = edgeById.get(edgeOf(to.lane) ?? "");
  if (!ea || !eb) return straight;
  const a = project(ea.path, ea.cum, [from.lng, from.lat]);
  const b = project(eb.path, eb.cum, [to.lng, to.lat]);
  if (a.off > MAX_SNAP_M || b.off > MAX_SNAP_M) return straight;
  if (ea === eb) return b.s >= a.s ? slice(ea.path, ea.cum, a.s, b.s) : straight;
  const exit = ea.path[ea.path.length - 1];
  const entry = eb.path[0];
  if (haversineMeters(exit, entry) > MAX_JOIN_M) return straight;
  return [...slice(ea.path, ea.cum, a.s, ea.lengthM), ...slice(eb.path, eb.cum, 0, b.s)];
}

/** The point a fraction `f` (0..1) of the way along `path`, by distance. */
export function sampleAlong(path: LngLat[], f: number): LngLat {
  if (path.length === 1) return path[0];
  const cum = cumulativeLengths(path);
  const q = pointAlongPath(path, cum, cum[cum.length - 1] * Math.max(0, Math.min(1, f)));
  return [q.lng, q.lat];
}
