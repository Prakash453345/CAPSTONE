/**
 * Pure event -> `NotificationEvent` classifiers for the live provider (Phase 5).
 * Kept separate from `wsProvider.ts`, same reasoning as `wsMappers.ts`: no
 * socket/timer state here, so every rule is testable with plain objects.
 *
 * Each classifier only fires on a genuine, narrow occurrence — never on a
 * routine per-tick update — so callers can push whatever comes back straight
 * onto the toast stack without their own spam-guarding. The specific detail
 * strings matched below (`"auto-reroute — "`, `"reroute held: "`) are literal
 * prefixes the backend actually emits (`sim_service/live/emergency_control.py`),
 * not guessed wording — if the backend ever changes them, the fallback is
 * simply "no notification", never a wrong one.
 */
import type {
  Anomaly,
  AnomalyStatus,
  EmergencyRequestState,
  EmergencyVehicleKind,
  NotificationEvent,
  NotificationTone,
} from "@/types";
import { roadLabel, shortJunctionName } from "@/data/network";
import { unitName } from "@/components/console/words";

const VEHICLE_LABEL: Record<EmergencyVehicleKind, string> = {
  ambulance: "Ambulance",
  fire_truck: "Fire truck",
  police: "Police unit",
};

function vehicleLabel(kind: EmergencyVehicleKind | undefined, vehicleId: string): string {
  // Crew units already read as names ("POL-2" -> "Police 2"); say that, not
  // "Police unit POL-2".
  const named = unitName(vehicleId);
  if (named !== vehicleId) return named;
  return kind ? `${VEHICLE_LABEL[kind]} ${vehicleId}` : vehicleId;
}

// ---------------------------------------------------------------- anomalies

const ANOMALY_CREATED_TONE: Record<Anomaly["severity"], NotificationTone> = {
  low: "info",
  medium: "warn",
  high: "critical",
  blocked: "critical",
};

/** Fires once when an anomaly first appears active, and once when a
 *  previously-active anomaly stops being active. A repeat update that leaves
 *  `status` unchanged (e.g. a severity edit) produces nothing. */
export function classifyAnomalyEvent(
  prevStatus: AnomalyStatus | undefined,
  anomaly: Anomaly,
  atMs: number,
): NotificationEvent | null {
  if (prevStatus === undefined && anomaly.status === "active") {
    return {
      id: `anomaly-created-${anomaly.id}-${atMs}`,
      kind: "anomaly-created",
      tone: ANOMALY_CREATED_TONE[anomaly.severity],
      title: "Anomaly reported",
      message: `${anomaly.severity} ${anomaly.kind.replace(/_/g, " ")} on ${roadLabel(anomaly.edgeId)}`,
      atMs,
      anomalyId: anomaly.id,
    };
  }
  if (prevStatus === "active" && anomaly.status !== "active") {
    return {
      id: `anomaly-cleared-${anomaly.id}-${atMs}`,
      kind: "anomaly-cleared",
      tone: "ok",
      title: "Anomaly cleared",
      message: `${anomaly.kind.replace(/_/g, " ")} on ${roadLabel(anomaly.edgeId)} is ${anomaly.status}`,
      atMs,
      anomalyId: anomaly.id,
    };
  }
  return null;
}

// ---------------------------------------------------------------- emergency requests

export interface EmergencyTransition {
  requestId: string;
  vehicleId: string;
  vehicleKind?: EmergencyVehicleKind;
  prevState: EmergencyRequestState | undefined;
  nextState: EmergencyRequestState;
  prevDetail: string;
  detail: string;
  actor: string;
}

const AUTO_REROUTE_PREFIX = "auto-reroute — ";
const REROUTE_HELD_PREFIX = "reroute held: ";

/**
 * Classifies one `EmergencyRequestUpdated` transition. Returns `null` for
 * anything that isn't one of the twelve named notification categories,
 * including the periodic heartbeat republish the backend sends for every
 * active request (`emergency_control.py::tick`'s `_REPUBLISH_INTERVAL_S`
 * loop) — that one carries an unchanged `state`+`detail`, which the guard
 * below drops before any rule runs.
 */
export function classifyEmergencyEvent(t: EmergencyTransition, atMs: number): NotificationEvent | null {
  const unchanged = t.prevState === t.nextState && t.detail === t.prevDetail;
  if (unchanged) return null;

  const who = vehicleLabel(t.vehicleKind, t.vehicleId);
  const isOperator = t.actor.startsWith("operator:");

  if (t.nextState === "cancelled") {
    // An operator-initiated CANCEL is their own visible action, not a failure
    // to flag; a system cancellation means the initial routing attempt failed.
    if (isOperator) return null;
    return {
      id: `route-failure-${t.requestId}-${atMs}`,
      kind: "route-failure",
      tone: "critical",
      title: "Route planning failed",
      message: `${who}: ${t.detail || "no route could be found"}`,
      atMs,
      requestId: t.requestId,
    };
  }

  if (t.nextState === "route_ready") {
    if (t.prevState === undefined || t.prevState === "created" || t.prevState === "routing") {
      return {
        id: `route-calculated-${t.requestId}-${atMs}`,
        kind: "route-calculated",
        tone: "info",
        title: "Route calculated",
        message: `${who} has a recommended route ready`,
        atMs,
        requestId: t.requestId,
      };
    }
    // route_ready -> route_ready: a REROUTE while not yet dispatched.
    if (isOperator) {
      return {
        id: `route-recalculated-${t.requestId}-${atMs}`,
        kind: "route-recalculated",
        tone: "info",
        title: "Route recalculated",
        message: `${who}: route updated by operator`,
        atMs,
        requestId: t.requestId,
      };
    }
    if (t.detail.startsWith(AUTO_REROUTE_PREFIX)) {
      return {
        id: `auto-reroute-${t.requestId}-${atMs}`,
        kind: "auto-reroute",
        tone: "warn",
        title: "Automatic reroute",
        message: `${who}: ${t.detail.slice(AUTO_REROUTE_PREFIX.length)}`,
        atMs,
        requestId: t.requestId,
      };
    }
    return null;
  }

  // In-flight reroute: state doesn't change (IN_TRANSIT/GREEN_CORRIDOR_ACTIVE
  // stay put) but `detail` does — the two outcomes the monitor can report.
  if (t.prevState === t.nextState) {
    if (t.detail.startsWith(AUTO_REROUTE_PREFIX)) {
      return {
        id: `auto-reroute-${t.requestId}-${atMs}`,
        kind: "auto-reroute",
        tone: "warn",
        title: "Automatic reroute",
        message: `${who}: ${t.detail.slice(AUTO_REROUTE_PREFIX.length)}`,
        atMs,
        requestId: t.requestId,
      };
    }
    if (t.detail.startsWith(REROUTE_HELD_PREFIX)) {
      return {
        id: `road-blocked-ahead-${t.requestId}-${atMs}`,
        kind: "road-blocked-ahead",
        tone: "critical",
        title: "Road blocked ahead",
        message: `${who}: ${t.detail.slice(REROUTE_HELD_PREFIX.length)} — holding current route`,
        atMs,
        requestId: t.requestId,
      };
    }
    return null;
  }

  if (t.nextState === "completed") {
    return {
      id: `emergency-vehicle-arrived-${t.requestId}-${atMs}`,
      kind: "emergency-vehicle-arrived",
      tone: "ok",
      title: "Emergency vehicle arrived",
      message: `${who} reached its destination`,
      atMs,
      requestId: t.requestId,
    };
  }

  // Any other transition (e.g. ROUTE_READY -> GREEN_CORRIDOR_ACTIVE, or a
  // plain DEPART) is either not one of the twelve categories or is already
  // covered by the corridor-event stream — stay quiet rather than duplicate.
  return null;
}

// ---------------------------------------------------------------- green corridor

export interface CorridorEventPayload {
  requestId: string;
  corridorId: string;
  /** `GreenCorridorEvent`: "proposed" | "activated" | "junction_passed" | "terminated". */
  event: string;
  /** The passed junction's id, for a `junction_passed` event (mirrors `mapCorridor`). */
  junctionId?: string;
}

/** Only "activated" and "junction_passed" are notify-worthy — "proposed" is
 *  visible on the map already and "terminated" is redundant with the
 *  request's own completed/cancelled transition. */
export function classifyCorridorEvent(p: CorridorEventPayload, atMs: number): NotificationEvent | null {
  if (p.event === "activated") {
    return {
      id: `corridor-activated-${p.corridorId}-${atMs}`,
      kind: "corridor-activated",
      tone: "info",
      title: "Green corridor activated",
      message: "Signals ahead of the vehicle are now being held green",
      atMs,
      requestId: p.requestId,
    };
  }
  if (p.event === "junction_passed" && p.junctionId) {
    return {
      id: `junction-passed-${p.corridorId}-${p.junctionId}-${atMs}`,
      kind: "junction-passed",
      tone: "info",
      title: "Junction cleared",
      message: `${shortJunctionName(p.junctionId)} cleared for the corridor`,
      atMs,
      requestId: p.requestId,
      intersectionId: p.junctionId,
    };
  }
  return null;
}

// ---------------------------------------------------------------- signals

const FAULT_LABEL: Record<string, string> = {
  comms_lost: "communication lost",
  conflict_monitor_trip: "conflict monitor trip",
  power_restart: "power restart",
  readback_divergence: "readback divergence",
  no_legal_plan: "no legal signal plan",
  interlock_rejected: "interlock rejected",
};

/** Every `SignalFaulted` is notify-worthy — there is no periodic/duplicate
 *  variant of it on the wire. */
export function classifySignalFault(
  p: { intersectionId: string; faultType: string; detail: string },
  atMs: number,
): NotificationEvent {
  return {
    id: `signal-fault-${p.intersectionId}-${atMs}`,
    kind: "signal-fault",
    tone: "critical",
    title: "Signal fault",
    message: `${shortJunctionName(p.intersectionId)}: ${FAULT_LABEL[p.faultType] ?? p.faultType}${
      p.detail ? ` — ${p.detail}` : ""
    }`,
    atMs,
    intersectionId: p.intersectionId,
  };
}

// ---------------------------------------------------------------- connection

/** `wasEverOnline` guards the very first cold connect from reading as a
 *  "recovery" — there was nothing to recover from. */
export function classifyConnectionEvent(
  prev: string,
  next: string,
  wasEverOnline: boolean,
  atMs: number,
): NotificationEvent | null {
  if (prev === next) return null;
  if (next === "reconnecting" && prev === "online") {
    return {
      id: `connection-lost-${atMs}`,
      kind: "connection-lost",
      tone: "critical",
      title: "Connection lost",
      message: "Live data stream disconnected — attempting to reconnect",
      atMs,
    };
  }
  if (next === "online" && wasEverOnline && (prev === "reconnecting" || prev === "offline")) {
    return {
      id: `connection-restored-${atMs}`,
      kind: "connection-restored",
      tone: "ok",
      title: "Connection restored",
      message: "Live data stream reconnected",
      atMs,
    };
  }
  return null;
}
