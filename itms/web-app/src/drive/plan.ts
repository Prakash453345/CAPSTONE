import { edgeById, junctionById, roadLabel, shortJunctionName } from "@/data/network";
import {
  angleDelta,
  bearingDeg,
  cumulativeLengths,
  haversineMeters,
  pointAlongPath,
  type LngLat,
} from "@/utils/geo";

/**
 * A dispatched route turned into what a driver needs on the road: one
 * continuous line to follow, the turns along it, and the signals it crosses.
 *
 * The backend hands over a list of SUMO edge ids. They carry no direction, so
 * the line is rebuilt by orienting each edge to join the one before it.
 */

export interface PlanSpan {
  edgeId: string;
  startM: number;
  endM: number;
  name: string;
}

export type ManeuverKind = "depart" | "turn" | "bear" | "uturn" | "continue" | "arrive";
export type ManeuverSide = "left" | "right" | "straight";

export interface Maneuver {
  id: string;
  /** Distance from the start of the route to where the maneuver happens. */
  atM: number;
  kind: ManeuverKind;
  side: ManeuverSide;
  sharp: boolean;
  /** The road you end up on. */
  road: string;
  /** "Turn left onto the primary road" */
  text: string;
}

export interface PlanSignal {
  junctionId: string;
  name: string;
  atM: number;
}

export interface RoutePlan {
  edgeIds: string[];
  coords: LngLat[];
  cum: number[];
  totalM: number;
  spans: PlanSpan[];
  maneuvers: Maneuver[];
  signals: PlanSignal[];
}

const STRAIGHT_BELOW_DEG = 20;
const BEAR_BELOW_DEG = 45;
const SHARP_ABOVE_DEG = 120;
const UTURN_ABOVE_DEG = 160;
/** A bend inside a single road only becomes an instruction when it is this sharp. */
const BEND_DEG = 60;
const SIGNAL_SNAP_M = 60;

const reversed = (p: LngLat[]): LngLat[] => [...p].reverse();

/** Each edge's points in travel order, joined end to start. */
export function orientedPaths(edgeIds: readonly string[]): { id: string; path: LngLat[] }[] {
  const edges = edgeIds.flatMap((id) => {
    const e = edgeById.get(id);
    return e ? [{ id, path: e.path as LngLat[] }] : [];
  });
  if (!edges.length) return [];

  const out: { id: string; path: LngLat[] }[] = [];
  const first = edges[0]!;
  let current = first.path;
  if (edges.length > 1) {
    const next = edges[1]!.path;
    const ends = [next[0]!, next[next.length - 1]!];
    const forward = Math.min(...ends.map((p) => haversineMeters(first.path[first.path.length - 1]!, p)));
    const backward = Math.min(...ends.map((p) => haversineMeters(first.path[0]!, p)));
    if (backward < forward) current = reversed(first.path);
  }
  out.push({ id: first.id, path: current });

  for (let i = 1; i < edges.length; i++) {
    const e = edges[i]!;
    const tail = out[out.length - 1]!.path;
    const end = tail[tail.length - 1]!;
    const asIs = haversineMeters(end, e.path[0]!);
    const flipped = haversineMeters(end, e.path[e.path.length - 1]!);
    out.push({ id: e.id, path: flipped < asIs ? reversed(e.path) : e.path });
  }
  return out;
}

const compass = (deg: number) =>
  (["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"] as const)[
    Math.round(deg / 45) % 8
  ]!;

/** "the primary road" for an unnamed class label, otherwise the street as named. */
export function roadPhrase(name: string): string {
  return /^(Service|Primary|Secondary|Tertiary|Trunk|Motorway)\b/.test(name) ? `the ${name.toLowerCase()}` : name;
}

function headingBetween(coords: LngLat[], cum: number[], fromM: number, toM: number): number {
  const a = pointAlongPath(coords, cum, fromM);
  const b = pointAlongPath(coords, cum, toM);
  return bearingDeg([a.lng, a.lat], [b.lng, b.lat]);
}

function describe(kind: ManeuverKind, side: ManeuverSide, sharp: boolean, road: string): string {
  const onto = roadPhrase(road);
  switch (kind) {
    case "depart":
      return `Start on ${onto}`;
    case "arrive":
      return "Arrive at the destination";
    case "uturn":
      return "Make a U-turn";
    case "continue":
      return `Continue onto ${onto}`;
    case "bear":
      return `Bear ${side} onto ${onto}`;
    case "turn":
      return sharp ? `Take a sharp ${side} onto ${onto}` : `Turn ${side} onto ${onto}`;
  }
}

function classify(delta: number): { kind: ManeuverKind; side: ManeuverSide; sharp: boolean } {
  const size = Math.abs(delta);
  const side: ManeuverSide = size < STRAIGHT_BELOW_DEG ? "straight" : delta > 0 ? "right" : "left";
  if (size < STRAIGHT_BELOW_DEG) return { kind: "continue", side, sharp: false };
  if (size > UTURN_ABOVE_DEG) return { kind: "uturn", side, sharp: true };
  if (size < BEAR_BELOW_DEG) return { kind: "bear", side, sharp: false };
  return { kind: "turn", side, sharp: size > SHARP_ABOVE_DEG };
}

/** Where a point sits along the route line, and how far off it is. */
export function projectOnPlan(
  plan: Pick<RoutePlan, "coords" | "cum">,
  point: LngLat,
  window?: { fromM: number; toM: number },
): { alongM: number; offRouteM: number } {
  const { coords, cum } = plan;
  const scale = Math.cos((point[1] * Math.PI) / 180);
  let best = { alongM: 0, offRouteM: Infinity };
  for (let i = 1; i < coords.length; i++) {
    if (window && (cum[i]! < window.fromM || cum[i - 1]! > window.toM)) continue;
    const a = coords[i - 1]!;
    const b = coords[i]!;
    const dx = (b[0] - a[0]) * scale;
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t =
      len2 === 0 ? 0 : Math.max(0, Math.min(1, (((point[0] - a[0]) * scale) * dx + (point[1] - a[1]) * dy) / len2));
    const snapped: LngLat = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    const d = haversineMeters(point, snapped);
    if (d < best.offRouteM) best = { alongM: cum[i - 1]! + (cum[i]! - cum[i - 1]!) * t, offRouteM: d };
  }
  return best;
}

/** Null when none of the route's edges are in the loaded network. */
export function buildPlan(edgeIds: readonly string[], signalJunctionIds: readonly string[] = []): RoutePlan | null {
  const parts = orientedPaths(edgeIds);
  if (!parts.length) return null;

  // A gap between two edges still gets a straight connector, so the driver
  // keeps one continuous line instead of a route that vanishes mid-way.
  const coords: LngLat[] = [];
  const startIdx: number[] = [];
  for (const part of parts) {
    const last = coords[coords.length - 1];
    const duplicate = last && haversineMeters(last, part.path[0]!) < 1;
    // The shared point (or the end of the connector) is where this edge begins.
    startIdx.push(Math.max(0, coords.length - 1));
    coords.push(...(duplicate ? part.path.slice(1) : part.path));
  }
  const cum = cumulativeLengths(coords);
  const totalM = cum[cum.length - 1] ?? 0;
  const spans: PlanSpan[] = parts.map((part, i) => ({
    edgeId: part.id,
    startM: i === 0 ? 0 : cum[startIdx[i]!]!,
    endM: i + 1 < parts.length ? cum[startIdx[i + 1]!]! : totalM,
    name: roadLabel(part.id),
  }));

  const maneuvers: Maneuver[] = [];
  const first = spans[0]!;
  maneuvers.push({
    id: "m-depart",
    atM: 0,
    kind: "depart",
    side: "straight",
    sharp: false,
    road: first.name,
    text: `Start on ${roadPhrase(first.name)}, heading ${compass(headingBetween(coords, cum, 0, Math.min(25, totalM)))}`,
  });

  for (let i = 1; i < spans.length; i++) {
    const at = spans[i]!.startM;
    const incoming = headingBetween(coords, cum, Math.max(0, at - 15), Math.max(0, at - 1));
    const outgoing = headingBetween(coords, cum, Math.min(totalM, at + 1), Math.min(totalM, at + 15));
    const c = classify(angleDelta(incoming, outgoing));
    const road = spans[i]!.name;
    // Going straight on to a road with the same name is not worth saying.
    if (c.kind === "continue" && road === spans[i - 1]!.name) continue;
    maneuvers.push({ id: `m-${i}`, atM: at, ...c, road, text: describe(c.kind, c.side, c.sharp, road) });
  }

  // Sharp bends inside one road (a hairpin, a roundabout's exit).
  const boundaries = spans.map((s) => s.startM);
  for (let d = 30; d < totalM - 30; d += 10) {
    if (boundaries.some((b) => Math.abs(b - d) < 30)) continue;
    const delta = angleDelta(headingBetween(coords, cum, d - 25, d - 2), headingBetween(coords, cum, d + 2, d + 25));
    if (Math.abs(delta) < BEND_DEG) continue;
    if (maneuvers.some((m) => Math.abs(m.atM - d) < 40)) continue;
    const span = spans.find((s) => d >= s.startM && d <= s.endM) ?? first;
    const c = classify(delta);
    maneuvers.push({ id: `b-${Math.round(d)}`, atM: d, ...c, road: span.name, text: describe(c.kind, c.side, c.sharp, span.name) });
  }

  maneuvers.push({
    id: "m-arrive",
    atM: totalM,
    kind: "arrive",
    side: "straight",
    sharp: false,
    road: spans[spans.length - 1]!.name,
    text: "Arrive at the destination",
  });
  maneuvers.sort((a, b) => a.atM - b.atM);

  const signals: PlanSignal[] = [];
  const seen = new Set<string>();
  for (const id of signalJunctionIds) {
    const j = junctionById.get(id);
    if (!j || seen.has(id)) continue;
    const hit = projectOnPlan({ coords, cum }, [j.lng, j.lat]);
    if (hit.offRouteM > SIGNAL_SNAP_M) continue;
    seen.add(id);
    signals.push({ junctionId: id, name: shortJunctionName(id), atM: hit.alongM });
  }
  signals.sort((a, b) => a.atM - b.atM);

  return { edgeIds: parts.map((p) => p.id), coords, cum, totalM, spans, maneuvers, signals };
}

/** The first maneuver still ahead of `alongM` (the arrival, at the very end). */
export function nextManeuver(plan: RoutePlan, alongM: number): Maneuver {
  return plan.maneuvers.find((m) => m.kind !== "depart" && m.atM > alongM + 3) ?? plan.maneuvers[plan.maneuvers.length - 1]!;
}

/** The maneuver after `next`, for the small "then ..." line. */
export function maneuverAfter(plan: RoutePlan, next: Maneuver): Maneuver | null {
  const i = plan.maneuvers.indexOf(next);
  return i >= 0 && i + 1 < plan.maneuvers.length ? plan.maneuvers[i + 1]! : null;
}

/** "300 m", "1.2 km" — rounded the way a driver wants to hear it. */
export function formatDistance(m: number): string {
  if (!Number.isFinite(m)) return "–";
  if (m < 950) return `${Math.max(0, Math.round(m / 10) * 10)} m`;
  return `${(m / 1000).toFixed(m < 9950 ? 1 : 0)} km`;
}

/** The part of the route between two distances, as a line (for drawing). */
export function slicePlan(plan: Pick<RoutePlan, "coords" | "cum" | "totalM">, fromM: number, toM: number): LngLat[] {
  const from = Math.max(0, Math.min(fromM, plan.totalM));
  const to = Math.max(from, Math.min(toM, plan.totalM));
  if (plan.coords.length < 2) return [...plan.coords];
  const start = pointAlongPath(plan.coords, plan.cum, from);
  const end = pointAlongPath(plan.coords, plan.cum, to);
  const inner = plan.coords.filter((_, i) => plan.cum[i]! > from && plan.cum[i]! < to);
  return [[start.lng, start.lat], ...inner, [end.lng, end.lat]];
}
