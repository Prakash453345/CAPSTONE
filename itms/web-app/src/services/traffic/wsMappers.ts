/**
 * Pure payload → view-model mappers for the live WebSocket provider. Kept
 * separate from `wsProvider.ts` (which owns sockets, timers and accumulation)
 * so this half can be unit-tested with plain objects.
 */
import type {
  CorridorReservationView,
  EmergencyRouteView,
  EmergencyVehicleLive,
  GreenCorridorStatus,
  GreenCorridorView,
  RequestTimelineEntry,
  VehicleType,
} from "@/types";

/** timestamp-millis fields arrive as ISO strings (api-service isoformats every
 *  datetime) or, defensively, as epoch-ms numbers. */
export function msToIso(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number") return new Date(v).toISOString();
  return new Date().toISOString();
}

/**
 * Fleet silhouette for a SUMO vehicle. The position event has no class field
 * (contracts/events/vehicle_position_updated.avsc), so this reads the id and
 * any optional `vtype` / `vehicle_class` producers may already attach. For a
 * generic SUMO id (for example `veh531`), a stable fleet-mix fallback gives
 * the operator meaningful silhouettes without inventing a changing type on
 * every update. It is presentation-only: SUMO position and speed data remain
 * untouched.
 */
export function inferVehicleType(vehicleId: string, vtype?: unknown): VehicleType {
  const blob = `${vehicleId} ${typeof vtype === "string" ? vtype : ""}`.toLowerCase();
  if (/(ambulance|emergency|\bamb\b)/.test(blob)) return "ambulance";
  if (/(motorcycle|moto|bike)/.test(blob)) return "motorcycle";
  if (/\b(bus|coach)\b/.test(blob) || blob.includes("veh_bus")) return "bus";
  if (/(truck|trailer|lorry|hgv)/.test(blob)) return "truck";
  if (typeof vtype === "string" && vtype.trim() !== "") return "car";
  return fleetTypeForGenericId(vehicleId);
}

/** A deterministic command-center fleet mix for streams that omit SUMO vType. */
function fleetTypeForGenericId(vehicleId: string): VehicleType {
  let hash = 2166136261;
  for (let i = 0; i < vehicleId.length; i += 1) {
    hash ^= vehicleId.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const bucket = (hash >>> 0) % 100;
  // Representative urban mix: mostly cars, then two-wheelers, commercial
  // vehicles and transit, with a deliberately sparse ambulance presence.
  if (bucket < 48) return "car";
  if (bucket < 70) return "motorcycle";
  if (bucket < 84) return "truck";
  if (bucket < 97) return "bus";
  return "ambulance";
}

export function toMs(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const t = Date.parse(v);
    return Number.isNaN(t) ? Date.now() : t;
  }
  return Date.now();
}

/** RouteSummary payload (emergency_request_updated.avsc) -> EmergencyRouteView. */
export function mapRoute(r: unknown): EmergencyRouteView | undefined {
  if (r == null || typeof r !== "object") return undefined;
  const o = r as Record<string, unknown>;
  const arr = (k: string): string[] =>
    Array.isArray(o[k]) ? (o[k] as unknown[]).map(String) : [];
  return {
    edges: arr("edges"),
    rank: Number(o.rank ?? 0),
    totalDistanceM: Number(o.total_distance_m ?? 0),
    totalTravelTimeS: Number(o.total_travel_time_s ?? 0),
    etaS: Number(o.eta_s ?? 0),
    nIntersections: Number(o.n_intersections ?? 0),
    signalisedIntersections: arr("signalised_intersections"),
    congestedSegments: arr("congested_segments"),
    anomalousSegmentsAvoided: arr("anomalous_segments_avoided"),
    forcedThrough: arr("forced_through"),
    reliable: Boolean(o.reliable),
    cost: {
      travelTimeS: Number(o.cost_travel_time_s ?? 0),
      congestion: Number(o.cost_congestion ?? 0),
      anomaly: Number(o.cost_anomaly ?? 0),
      signalDelayS: Number(o.cost_signal_delay_s ?? 0),
      disruption: Number(o.cost_disruption ?? 0),
      reliability: Number(o.cost_reliability ?? 0),
      score: Number(o.route_score ?? 0),
    },
    weightsUsed:
      o.weights_used && typeof o.weights_used === "object"
        ? Object.fromEntries(
            Object.entries(o.weights_used as Record<string, unknown>).map(([k, v]) => [
              k,
              Number(v),
            ]),
          )
        : {},
  };
}

/** GreenCorridorUpdated payload -> GreenCorridorView (without the running
 *  passed-junction set, which the provider accumulates via `mergePassed`). */
export function mapCorridor(p: Record<string, unknown>): GreenCorridorView {
  const rows = Array.isArray(p.reservations) ? (p.reservations as unknown[]) : [];
  const reservations: CorridorReservationView[] = rows.map((row) => {
    const o = (row ?? {}) as Record<string, unknown>;
    return {
      intersectionId: String(o.intersection_id ?? ""),
      movements: Array.isArray(o.movements) ? (o.movements as unknown[]).map(String) : [],
      openAtMs: Number(o.open_at_ms ?? 0),
      closeAtMs: Number(o.close_at_ms ?? 0),
      order: Number(o.order ?? 0),
    };
  });
  const passed =
    p.event === "junction_passed" && typeof p.detail === "string" ? [p.detail] : [];
  return {
    corridorId: String(p.corridor_id ?? ""),
    status: String(p.status ?? "proposed").toLowerCase() as GreenCorridorStatus,
    reservations,
    passedIntersections: passed,
    peakConcurrency: Number(p.peak_concurrency ?? 0),
  };
}

/** Union of the prior running set with whatever the latest corridor event named. */
export function mergePassed(prior: string[] | undefined, next: string[]): string[] {
  return [...new Set([...(prior ?? []), ...next])];
}

/** EmergencyVehicleUpdated payload -> EmergencyVehicleLive. */
export function mapVehicleLive(p: Record<string, unknown>): EmergencyVehicleLive {
  return {
    lat: p.lat == null ? undefined : Number(p.lat),
    lon: p.lon == null ? undefined : Number(p.lon),
    edgeId: p.edge_id == null ? undefined : String(p.edge_id),
    speedMps: Number(p.speed_mps ?? 0),
    etaS: p.eta_s == null ? undefined : Number(p.eta_s),
    routeProgress: Number(p.route_progress ?? 0),
    status: String(p.status ?? "en_route").toLowerCase() as EmergencyVehicleLive["status"],
  };
}

const MAX_TIMELINE = 16;

/**
 * Append an activity-log entry when it represents genuine movement — a state
 * change, or a fresh `detail` line on the same state. A repeat of the last
 * entry (e.g. a monitor heartbeat) is dropped. Returns a new array.
 */
export function pushTimelineEntry(
  prior: RequestTimelineEntry[] | undefined,
  entry: RequestTimelineEntry,
): RequestTimelineEntry[] {
  const out = prior ? [...prior] : [];
  const last = out[out.length - 1];
  const isNew =
    !last ||
    last.state !== entry.state ||
    (entry.detail !== "" && entry.detail !== last.detail);
  if (isNew) {
    out.push(entry);
    if (out.length > MAX_TIMELINE) out.shift();
  }
  return out;
}
