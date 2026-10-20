import { roadLabel } from "@/data/network";
import { anomalyWord } from "@/components/console/words";
import type { Tone } from "@/components/console/tone";
import type { Anomaly, EmergencyRequest, GreenCorridorView, Intersection } from "@/types";
import { projectOnPlan, type RoutePlan } from "@/crew/plan";

/** What a crew should make of the next signals on the route. */
export type SignalStatus = "held" | "arranged" | "green" | "amber" | "red" | "fault" | "unknown";

export interface UpcomingSignal {
  junctionId: string;
  name: string;
  distM: number;
  status: SignalStatus;
  /** One line a crew reads at a glance. */
  label: string;
  tone: Tone;
}

const SIGNAL_WORDS: Record<SignalStatus, { label: string; tone: Tone }> = {
  held: { label: "Green held for you", tone: "ok" },
  arranged: { label: "Clearing as you approach", tone: "info" },
  green: { label: "Green, not held for you", tone: "ok" },
  amber: { label: "Amber: be ready to stop", tone: "warn" },
  red: { label: "Red, not cleared: slow down", tone: "critical" },
  fault: { label: "Signal fault: proceed with caution", tone: "critical" },
  unknown: { label: "No signal reading", tone: "neutral" },
};

/**
 * The signal's status for this crew. A junction the green corridor holds
 * outranks its ordinary colour; a fault outranks everything, because a held
 * or green light is not safe to trust at a junction that has lost control.
 * The plain colours are the console's approximation, not a per-approach phase.
 */
export function signalStatus(
  intersection: Intersection | undefined,
  corridor: GreenCorridorView | undefined,
  junctionId: string,
): SignalStatus {
  if (intersection?.fault) return "fault";
  if (intersection?.preempted) return "held";
  const reserved = corridor?.reservations.some((r) => r.intersectionId === junctionId);
  if (reserved) return "arranged";
  if (!intersection) return "unknown";
  return intersection.signalState === "green" ? "green" : intersection.signalState === "yellow" ? "amber" : "red";
}

export function upcomingSignals(
  plan: RoutePlan,
  alongM: number,
  ctx: { intersections: readonly Intersection[]; corridor?: GreenCorridorView; limit?: number },
): UpcomingSignal[] {
  const byId = new Map(ctx.intersections.map((i) => [i.id, i]));
  const passed = new Set(ctx.corridor?.passedIntersections ?? []);
  return plan.signals
    .filter((s) => s.atM > alongM - 5 && !passed.has(s.junctionId))
    .slice(0, ctx.limit ?? 4)
    .map((s) => {
      const status = signalStatus(byId.get(s.junctionId), ctx.corridor, s.junctionId);
      return { junctionId: s.junctionId, name: s.name, distM: Math.max(0, s.atM - alongM), status, ...SIGNAL_WORDS[status] };
    });
}

export type HazardKind = "closure" | "disruption" | "congestion" | "signal-fault" | "unit";

export interface Hazard {
  id: string;
  kind: HazardKind;
  distM: number;
  title: string;
  detail: string;
  tone: Tone;
}

const HEAVY_CONGESTION = 0.6;

/**
 * Everything on the remaining route worth a crew's attention, nearest first:
 * blocked or disrupted roads, heavy congestion, signals that have faulted and
 * other emergency units sharing the road.
 */
export function hazardsAhead(
  plan: RoutePlan,
  alongM: number,
  ctx: {
    anomalies: readonly Anomaly[];
    congestion: Readonly<Record<string, number>>;
    intersections: readonly Intersection[];
    requests: readonly EmergencyRequest[];
    ownRequestId?: string;
    horizonM?: number;
    unitNames?: (vehicleId: string) => string;
  },
): Hazard[] {
  const horizon = ctx.horizonM ?? 2000;
  const out: Hazard[] = [];
  const ahead = plan.spans.filter((s) => s.endM > alongM);

  for (const a of ctx.anomalies) {
    if (a.status !== "active") continue;
    const span = ahead.find((s) => s.edgeId === a.edgeId);
    if (!span) continue;
    const distM = Math.max(0, span.startM - alongM);
    if (distM > horizon) continue;
    const blocked = a.severity === "blocked" || a.estimatedImpact >= 1;
    out.push({
      id: `anomaly-${a.id}`,
      kind: blocked ? "closure" : "disruption",
      distM,
      title: `${anomalyWord(a.kind)} on ${roadLabel(a.edgeId)}`,
      detail: blocked ? "Road blocked: expect a new route" : `${Math.round(a.estimatedImpact * 100)}% of capacity lost`,
      tone: blocked || a.severity === "high" ? "critical" : "warn",
    });
  }

  for (const span of ahead) {
    const level = ctx.congestion[span.edgeId] ?? 0;
    if (level < HEAVY_CONGESTION) continue;
    const distM = Math.max(0, span.startM - alongM);
    if (distM > horizon) continue;
    // A closure on the same road already says it.
    if (out.some((h) => h.id === `anomaly-${span.edgeId}`)) continue;
    out.push({
      id: `congestion-${span.edgeId}`,
      kind: "congestion",
      distM,
      title: `Heavy traffic on ${roadLabel(span.edgeId)}`,
      detail: "Expect to slow down; other vehicles are being asked to give way",
      tone: "warn",
    });
  }

  const byId = new Map(ctx.intersections.map((i) => [i.id, i]));
  for (const s of plan.signals) {
    if (s.atM <= alongM || s.atM - alongM > horizon) continue;
    const fault = byId.get(s.junctionId)?.fault;
    if (!fault) continue;
    out.push({
      id: `fault-${s.junctionId}`,
      kind: "signal-fault",
      distM: s.atM - alongM,
      title: `Signal fault at ${s.name}`,
      detail: "Treat it as an uncontrolled junction",
      tone: "critical",
    });
  }

  for (const req of ctx.requests) {
    if (req.id === ctx.ownRequestId || req.state === "completed" || req.state === "cancelled") continue;
    const lat = req.live?.lat;
    const lon = req.live?.lon;
    if (lat == null || lon == null) continue;
    const hit = projectOnPlan(plan, [lon, lat]);
    if (hit.offRouteM > 60 || hit.alongM <= alongM - 20 || hit.alongM - alongM > horizon) continue;
    const name = ctx.unitNames?.(req.vehicleId) ?? req.vehicleId;
    out.push({
      id: `unit-${req.id}`,
      kind: "unit",
      distM: Math.max(0, hit.alongM - alongM),
      title: `${name} is on your route`,
      detail: hit.alongM >= alongM ? "Ahead of you: keep your distance" : "Close behind you",
      tone: "info",
    });
  }

  return out.sort((a, b) => a.distM - b.distM);
}

/** Where along the route a vehicle is, using its position when it has one. */
export function alongFor(
  plan: RoutePlan,
  live: EmergencyRequest["live"],
  previousM = 0,
): { alongM: number; offRouteM: number } {
  if (live?.lat != null && live?.lon != null) {
    // Search near where we were last so a route that doubles back (an
    // out-and-back) cannot snap the vehicle to the wrong pass.
    const near = projectOnPlan(plan, [live.lon, live.lat], { fromM: Math.max(0, previousM - 150), toM: previousM + 800 });
    if (near.offRouteM <= 60) return near;
    return projectOnPlan(plan, [live.lon, live.lat]);
  }
  const fraction = Math.max(0, Math.min(1, live?.routeProgress ?? 0));
  return { alongM: fraction * plan.totalM, offRouteM: 0 };
}

/** Seconds left: the unit's own estimate when it has one, otherwise a rough one. */
export function remainingSeconds(req: EmergencyRequest, remainingM: number): number | null {
  const own = req.live?.etaS ?? req.etaS;
  if (own != null && Number.isFinite(own)) return Math.max(0, own);
  const speed = req.live?.speedMps && req.live.speedMps > 1 ? req.live.speedMps : null;
  if (speed) return remainingM / speed;
  const planned = req.route;
  return planned && planned.totalDistanceM > 0 ? (planned.etaS * remainingM) / planned.totalDistanceM : null;
}

/** True once the vehicle is at the destination, whichever way that is reported. */
export function hasArrived(req: EmergencyRequest, remainingM: number): boolean {
  return req.state === "completed" || req.live?.status === "arrived" || remainingM < 25;
}

/** Traffic on one stretch of the route, Google Maps' way: free, slow or heavy. */
export type TrafficLevel = "free" | "slow" | "heavy";
export interface TrafficStretch {
  startM: number;
  endM: number;
  level: TrafficLevel;
}

const SLOW_TRAFFIC = 0.4;

export function trafficLevel(congestion: number): TrafficLevel {
  return congestion >= HEAVY_CONGESTION ? "heavy" : congestion >= SLOW_TRAFFIC ? "slow" : "free";
}

/** The route cut into stretches of equal traffic, merging neighbours alike. */
export function trafficAlong(plan: RoutePlan, congestion: Readonly<Record<string, number>>): TrafficStretch[] {
  const out: TrafficStretch[] = [];
  for (const span of plan.spans) {
    if (span.endM <= span.startM) continue;
    const level = trafficLevel(congestion[span.edgeId] ?? 0);
    const last = out[out.length - 1];
    if (last && last.level === level && Math.abs(last.endM - span.startM) < 1) last.endM = span.endM;
    else out.push({ startM: span.startM, endM: span.endM, level });
  }
  return out;
}

/** One line about the traffic still ahead: the first slow stretch, or clear. */
export function trafficAhead(stretches: readonly TrafficStretch[], alongM: number): string {
  const ahead = stretches.filter((s) => s.endM > alongM && s.level !== "free");
  if (!ahead.length) return "Traffic is clear to the destination";
  const first = ahead[0]!;
  const inM = Math.max(0, first.startM - alongM);
  const lenM = first.endM - Math.max(first.startM, alongM);
  const what = first.level === "heavy" ? "Heavy traffic" : "Slow traffic";
  const len = lenM >= 1000 ? `${(lenM / 1000).toFixed(1)} km` : `${Math.round(lenM / 10) * 10} m`;
  if (inM < 30) return `${what} now, for ${len}`;
  const dist = inM >= 1000 ? `${(inM / 1000).toFixed(1)} km` : `${Math.round(inM / 10) * 10} m`;
  return `${what} in ${dist}, for ${len}`;
}
