/**
 * Core domain types for TRAFFIX.
 *
 * These mirror the eventual ITMS backend contracts (contracts/events/*.avsc) but
 * stay UI-owned: the data layer normalises backend events into these shapes so
 * screens never depend on wire format. Section 12 of the build spec.
 */

// ---------------------------------------------------------------- geo
export interface LatLng {
  latitude: number;
  longitude: number;
}

// ---------------------------------------------------------------- vehicles
export type VehicleType = "car" | "bus" | "truck" | "motorcycle" | "ambulance";

export interface Vehicle extends LatLng {
  id: string;
  type: VehicleType;
  /** Ground speed, km/h (normalised from the backend's m/s). */
  speed: number;
  /** Compass bearing, 0–360. */
  heading: number;
  lane?: string;
  /** ISO 8601 timestamp of this observation. */
  timestamp: string;
}

// ---------------------------------------------------------------- incidents
export type IncidentType = "breakdown" | "collision" | "congestion" | "unknown";
export type IncidentSeverity = "low" | "medium" | "high" | "critical";
/** candidate = detector output, confirmed = operator-verified, resolved = cleared. */
export type IncidentStatus = "candidate" | "confirmed" | "resolved";

export interface Incident extends LatLng {
  id: string;
  type: IncidentType;
  severity: IncidentSeverity;
  /** Detector confidence, 0–1. */
  confidence: number;
  detectedAt: string;
  status: IncidentStatus;
  affectedIntersection?: string;
  /** False when the detector contract does not supply a severity. */
  severityKnown?: boolean;
  resolution?: string;
}

// ---------------------------------------------------------------- anomalies
/**
 * The normalised on-network anomaly — mirrors contracts/events/anomaly_updated.avsc.
 * Distinct from `Incident` (the M6 detection lifecycle): an anomaly is "there is
 * a disruption on this edge right now", from any source. `source` is what tells
 * an operator-created one apart from an auto-detected one.
 */
export type AnomalySource = "operator" | "sumo_injector" | "graph_model" | "vision";
export type AnomalyKind =
  | "accident"
  | "vehicle_breakdown"
  | "lane_blockage"
  | "road_obstruction"
  | "heavy_congestion"
  | "stalled_vehicle"
  | "fire"
  | "unknown";
export type AnomalySeverity = "low" | "medium" | "high" | "blocked";
export type AnomalyStatus = "active" | "resolved" | "cancelled";

export interface Anomaly {
  id: string;
  source: AnomalySource;
  kind: AnomalyKind;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  /** SUMO edge id this anomaly sits on. */
  edgeId: string;
  laneId?: string;
  /** 0–1 fraction of the edge's normal speed/capacity lost. 1 = blocked. */
  estimatedImpact: number;
  /** ISO 8601. */
  startTime: string;
  /** ISO 8601, when a time-boxed anomaly auto-clears; absent = open-ended. */
  expiresAt?: string;
  detail?: string;
  operator?: string;
}

// ---------------------------------------------------------------- intersections
export type SignalState = "red" | "yellow" | "green";

/** A recent `SignalFaulted` for this junction — mirrors the arbiter's own
 *  failsafe branches (`comms_lost`, `conflict_monitor_trip`, `power_restart`,
 *  `readback_divergence`, `no_legal_plan`, `interlock_rejected`). The arbiter
 *  emits exactly one of `SignalChanged`/`SignalFaulted` per tick, so a fresh
 *  `SignalChanged` for the same junction is itself proof of recovery — this
 *  clears the moment that arrives (see `wsProvider`), not on a guessed timer. */
export interface SignalFault {
  faultType: string;
  detail: string;
  atMs: number;
}

export interface Intersection extends LatLng {
  id: string;
  name: string;
  queueLength: number;
  averageSpeed: number;
  vehicleCount: number;
  signalState: SignalState;
  /** True while the most recent `SignalChanged` for this junction carried
   *  `source: "corridor_preemption"` — the arbiter is (or just was) holding
   *  it for an emergency vehicle, as opposed to its normal strategy. Always
   *  `false` in Sim mode, which has no arbiter. */
  preempted?: boolean;
  /** Present while the junction is in a failsafe state. Always absent in Sim
   *  mode, which has no arbiter to fault. */
  fault?: SignalFault;
}

// -------------------------------------------------- emergency requests / routes
export type EmergencyVehicleKind = "ambulance" | "fire_truck" | "police";
export type EmergencyRequestState =
  | "created"
  | "routing"
  | "route_ready"
  | "green_corridor_active"
  | "in_transit"
  | "completed"
  | "cancelled";

/** Mirrors the `route` field of contracts/events/emergency_request_updated.avsc. */
export interface EmergencyRouteView {
  edges: string[];
  rank: number;
  totalDistanceM: number;
  totalTravelTimeS: number;
  etaS: number;
  nIntersections: number;
  signalisedIntersections: string[];
  congestedSegments: string[];
  anomalousSegmentsAvoided: string[];
  /** Edges this route had to cross despite being flagged BLOCKED, because no
   *  alternative existed at all -- the operator's only physical route.
   *  Non-empty implies `reliable` is false. Always empty otherwise. */
  forcedThrough: string[];
  reliable: boolean;
  cost: {
    travelTimeS: number;
    congestion: number;
    anomaly: number;
    signalDelayS: number;
    disruption: number;
    reliability: number;
    score: number;
  };
  weightsUsed: Record<string, number>;
}

/** One junction's slice of a green corridor — mirrors a `reservations` entry of
 *  contracts/events/green_corridor_updated.avsc. */
export interface CorridorReservationView {
  intersectionId: string;
  movements: string[];
  openAtMs: number;
  closeAtMs: number;
  order: number;
}

export type GreenCorridorStatus =
  | "proposed"
  | "active"
  | "restoring"
  | "completed"
  | "cancelled";

export interface GreenCorridorView {
  corridorId: string;
  status: GreenCorridorStatus;
  reservations: CorridorReservationView[];
  passedIntersections: string[];
  peakConcurrency: number;
}

/** One entry in a request's activity log, accumulated client-side from the
 *  `emergency.request-updated` stream (the backend chain isn't sent whole). */
export interface RequestTimelineEntry {
  state: EmergencyRequestState;
  detail: string;
  actor: string;
  atMs: number;
}

export interface EmergencyRequest {
  id: string;
  vehicleId: string;
  vehicleKind: EmergencyVehicleKind;
  state: EmergencyRequestState;
  sourceEdge: string;
  destinationEdge: string;
  etaS?: number;
  greenCorridorId?: string;
  route?: EmergencyRouteView;
  alternatives: EmergencyRouteView[];
  corridor?: GreenCorridorView;
  /** Live position of the vehicle while it is driving (from `emergency.vehicle-updated`). */
  live?: EmergencyVehicleLive;
  timeline: RequestTimelineEntry[];
  detail?: string;
  updatedAt: string;
}

export interface EmergencyVehicleLive {
  lat?: number;
  lon?: number;
  edgeId?: string;
  speedMps: number;
  etaS?: number;
  routeProgress: number; // 0..1
  status: "idle" | "assigned" | "en_route" | "arrived";
}

// ---------------------------------------------------------------- system
export type ConnectionStatus =
  | "connecting"
  | "online"
  | "reconnecting"
  | "offline";

export type DataMode = "live" | "simulation";

export type ViewMode = "single" | "split";

export type WorkspaceId =
  | "overview"
  | "anomalies"
  | "traffic"
  | "emergency"
  | "analytics"
  | "settings";

export interface SystemSummary {
  operational: boolean;
  vehicleCount: number;
  /** 0–1 network congestion index. */
  congestion: number;
  signalsOnline: number;
  signalsTotal: number;
  /** ISO timestamp of the last accepted update from the data layer. */
  lastUpdate: string | null;
}

// ---------------------------------------------------------------- notifications
/**
 * A UI-only concept (no backend mirror): a noteworthy thing that just
 * happened, surfaced as a toast + a bell-dropdown history entry even when the
 * relevant panel isn't the one currently open. Deliberately narrow — routine
 * per-tick updates (vehicle positions, congestion, a heartbeat republish of an
 * unchanged request) never produce one; see `services/traffic/notifications.ts`
 * for what does.
 */
export type NotificationKind =
  | "anomaly-created"
  | "anomaly-cleared"
  | "route-calculated"
  | "route-recalculated"
  | "auto-reroute"
  | "road-blocked-ahead"
  | "corridor-activated"
  | "junction-passed"
  | "emergency-vehicle-arrived"
  | "route-failure"
  | "signal-fault"
  | "connection-lost"
  | "connection-restored";

/** Same vocabulary as `StatusDot`'s tone, minus "neutral" — every notification
 *  carries a meaning worth colouring. */
export type NotificationTone = "critical" | "warn" | "info" | "ok";

export interface NotificationEvent {
  /** Stable across a re-render of the same underlying occurrence, so the
   *  toaster and history list can dedupe/key on it. */
  id: string;
  kind: NotificationKind;
  tone: NotificationTone;
  title: string;
  message: string;
  /** When it happened, wall-clock ms (client receipt time for live events). */
  atMs: number;
  /** Present when clicking the toast should focus a specific request/anomaly/
   *  junction — the toaster and bell dropdown use these for cross-nav. */
  requestId?: string;
  anomalyId?: string;
  intersectionId?: string;
}
