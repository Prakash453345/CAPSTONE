/** Lightweight geodesy helpers for the map + mock simulator. Coordinates are [lng, lat]. */

export type LngLat = [number, number];

const R = 6_371_000; // Earth radius, metres
const toRad = (d: number) => (d * Math.PI) / 180;
const toDeg = (r: number) => (r * 180) / Math.PI;

/** Great-circle distance in metres between two [lng, lat] points. */
export function haversineMeters(a: LngLat, b: LngLat): number {
  const dLat = toRad(b[1] - a[1]);
  const dLng = toRad(a[0] - b[0]) * -1;
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial compass bearing (0–360, 0 = north) from a to b. */
export function bearingDeg(a: LngLat, b: LngLat): number {
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const dLng = toRad(b[0] - a[0]);
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** Per-vertex cumulative distance along a polyline; last entry is total length. */
export function cumulativeLengths(path: LngLat[]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) {
    out.push(out[i - 1] + haversineMeters(path[i - 1], path[i]));
  }
  return out;
}

export interface PointOnPath {
  lng: number;
  lat: number;
  /** Heading of the segment the point sits on. */
  headingDeg: number;
  /** Segment index the point sits on. */
  segment: number;
}

/**
 * Position `distanceM` along `path` (clamped to its ends). `cum` is the
 * output of cumulativeLengths(path), passed in so callers can cache it.
 */
export function pointAlongPath(
  path: LngLat[],
  cum: number[],
  distanceM: number,
): PointOnPath {
  const total = cum[cum.length - 1];
  const d = Math.max(0, Math.min(distanceM, total));

  let seg = 1;
  while (seg < cum.length - 1 && cum[seg] < d) seg++;

  const segStart = cum[seg - 1];
  const segLen = cum[seg] - segStart || 1;
  const t = (d - segStart) / segLen;

  const a = path[seg - 1];
  const b = path[seg];
  return {
    lng: a[0] + (b[0] - a[0]) * t,
    lat: a[1] + (b[1] - a[1]) * t,
    headingDeg: bearingDeg(a, b),
    segment: seg - 1,
  };
}

/** Shortest signed angular difference a→b in degrees, range (-180, 180]. */
export function angleDelta(a: number, b: number): number {
  let diff = ((b - a + 180) % 360) - 180;
  if (diff <= -180) diff += 360;
  return diff;
}
