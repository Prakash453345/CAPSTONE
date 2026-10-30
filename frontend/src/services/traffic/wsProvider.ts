/**
 * Real backend data provider: subscribes to the api-service WebSocket
 * (`/v1/stream`), accumulates the per-event stream into current state, and
 * emits a normalised `TrafficSnapshot` on a fixed cadence — the same shape the
 * mock provider produces, so stores and screens don't know the difference.
 *
 * Backend events consumed (decoded EventEnvelopes):
 *   VehiclePositionUpdated  -> vehicles + per-intersection vehicle stats
 *   ApproachState           -> roadCongestion (edge occupancy)
 *   SignalChanged           -> per-junction controller liveness (deliberate
 *                              simplification: a junction with a recent
 *                              SignalChanged is shown "green" = under active
 *                              control, else "red"; real per-approach phase
 *                              colouring needs the phase->movement map exported,
 *                              a later refinement) + `preempted` from the
 *                              decision's `source` — "corridor_preemption"
 *                              means the arbiter is holding it for an
 *                              emergency vehicle right now, anything else is
 *                              its normal strategy (e.g. Webster)
 *   AnomalyUpdated          -> anomalies (operator + injector + model, normalised)
 *   EmergencyRequestUpdated -> emergencyRequests (lifecycle + route + alternatives)
 *   GreenCorridorUpdated    -> emergencyRequests[].corridor
 *   SignalFaulted           -> intersections[].fault (cleared the moment a
 *                              SignalChanged for the same junction arrives —
 *                              the arbiter emits exactly one of the two per
 *                              tick, so that's proof of recovery, not a guess)
 *
 * Every handled event is also run through `services/traffic/notifications.ts`
 * to detect the narrow set of things worth a toast (Phase 5) — pushed onto
 * `pendingEvents` and drained into each snapshot's `events` field.
 *
 * IncidentCandidate / IncidentDetected / IncidentUpdated feed the incident
 * review workspace. Only received traffic observations advance lastUpdate;
 * neither socket-open nor the snapshot timer is evidence of fresh telemetry.
 */
import type {
  Anomaly,
  AnomalyKind,
  AnomalySeverity,
  AnomalySource,
  AnomalyStatus,
  EmergencyRequest,
  EmergencyRequestState,
  EmergencyRouteView,
  EmergencyVehicleKind,
  Incident,
  Intersection,
  NotificationEvent,
  SignalState,
  SystemSummary,
  Vehicle,
} from "@/types";
import { shortJunctionName, signalJunctions } from "@/data/network";
import type {
  ProviderStatus,
  TrafficDataProvider,
  TrafficSnapshot,
} from "@/services/traffic/types";
import { postCommand, type CommandResult, type OperatorCommand } from "@/services/traffic/commands";
import {
  inferVehicleType,
  mapCorridor,
  mapRoute,
  mapVehicleLive,
  mergePassed,
  msToIso,
  pushTimelineEntry,
  toMs,
} from "@/services/traffic/wsMappers";
import {
  classifyAnomalyEvent,
  classifyCorridorEvent,
  classifyEmergencyEvent,
  classifySignalFault,
} from "@/services/traffic/notifications";
import { junctionVehicleStats } from "@/services/traffic/intersectionStats";
import { mapIncident } from "@/services/traffic/incidents";
import { useCrewStore } from "@/store/crewStore";

const SNAPSHOT_MS = 500;
/** Drop a vehicle / edge reading not refreshed within this long. */
const ENTRY_STALE_MS = 8_000;
/** A junction with a SignalChanged newer than this is "under active control". */
const SIGNAL_FRESH_MS = 6_000;
/** A completed/cancelled request is kept around this long after its terminal
 *  update — long enough for the operator to read its mission summary and
 *  dismiss it (`emergencyStore.archiveRequest`) at their own pace. This is a
 *  memory safety net for a long-running session, not the primary way a
 *  finished mission leaves the roster; it used to be 6s, which routinely beat
 *  the operator to it. */
const TERMINAL_REQUEST_TTL_MS = 20 * 60_000;
/** The backend re-announces every live request every 10 s of simulation
 *  time. A live request it has stopped mentioning for this long, while the
 *  stream is otherwise flowing, no longer exists there (the simulation run
 *  restarted, or the backend did, while this tab stayed open), so it is
 *  dropped instead of being drawn forever. Not applied while the stream is
 *  quiet: a dropped connection must not erase what the operator was looking at. */
const ORPHAN_REQUEST_MS = 45_000;
const STREAM_LIVE_MS = 5_000;
/** Safety-net TTL for a tracked fault that never got an explicit recovering
 *  `SignalChanged` (the normal, immediate clear path — see `signalFaults`). */
const SIGNAL_FAULT_TTL_MS = 5 * 60_000;
const RECONNECT_MS = [1_000, 2_000, 4_000, 5_000];

function wsUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL as string | undefined;
  if (explicit) return explicit;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws/v1/stream`;
}

interface VehEntry {
  lat: number;
  lon: number;
  speedMps: number;
  heading: number;
  edgeId: string;
  type: Vehicle["type"];
  at: number;
}
interface EdgeEntry {
  occupancy: number;
  at: number;
}

interface Envelope {
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export function createWebSocketProvider(): TrafficDataProvider {
  const snapshotListeners = new Set<(s: TrafficSnapshot) => void>();
  const statusListeners = new Set<(s: ProviderStatus) => void>();

  const detectorIncidents = new Map<string, Incident>();
  const vehicles = new Map<string, VehEntry>();
  const edges = new Map<string, EdgeEntry>();
  /** intersection_id -> the arbiter decision that last commanded it. `source`
   *  is "corridor_preemption" while a green corridor holds this junction for
   *  an emergency vehicle, its normal strategy's name otherwise. */
  const signalSeenAt = new Map<string, { at: number; source: string }>();
  /** intersection_id -> its most recent `SignalFaulted`, cleared the moment a
   *  `SignalChanged` for the same junction arrives (Phase 10 — see the
   *  `SignalFault` doc comment for why that's a sound recovery signal). */
  const signalFaults = new Map<string, { faultType: string; detail: string; at: number }>();
  /** anomaly_id -> latest state. Terminal ones are kept briefly then dropped. */
  const anomalies = new Map<string, Anomaly & { _at: number }>();
  /** request_id -> latest emergency request. */
  const emergencyRequests = new Map<string, EmergencyRequest & { _at: number }>();
  /** Notable events detected this tick, drained into each snapshot then
   *  cleared — mirrors the backend's own `drain_events()` idiom. */
  let pendingEvents: NotificationEvent[] = [];

  let ws: WebSocket | null = null;
  let snapshotTimer: number | null = null;
  let reconnectTimer: number | null = null;
  let reconnectTries = 0;
  // Receipt time anchors per-entity expiry only. It is deliberately *not*
  // connection health: a quiet but open WebSocket is still a live connection.
  let lastMessageAt = 0;
  let lastTelemetryAt = 0;
  let status: ProviderStatus = "offline";
  let stopped = true;

  function setStatus(next: ProviderStatus) {
    if (status === next) return;
    status = next;
    for (const l of statusListeners) l(next);
  }

  function handleEnvelope(env: Envelope) {
    lastMessageAt = Date.now();
    const p = env.payload;
    switch (env.event_type) {
      case "IncidentCandidate":
      case "IncidentDetected":
      case "IncidentUpdated": {
        const id = String(p.incident_id);
        const incident = mapIncident(env.event_type === "IncidentDetected" ? { ...p, state: "CONFIRMED" } : p, detectorIncidents.get(id));
        if (incident) detectorIncidents.set(id, incident);
        // Keep session memory bounded; the canonical registry remains available via REST.
        if (detectorIncidents.size > 1000) detectorIncidents.delete(detectorIncidents.keys().next().value!);
        break;
      }
      case "VehiclePositionUpdated": {
        if (typeof p.vehicle_id !== "string" || ![p.lat, p.lon, p.speed_mps, p.heading_deg].every((v) => typeof v === "number" && Number.isFinite(v))) break;
        if (Math.abs(Number(p.lat)) > 90 || Math.abs(Number(p.lon)) > 180) break;
        lastTelemetryAt = lastMessageAt;
        const id = String(p.vehicle_id);
        vehicles.set(id, {
          lat: Number(p.lat),
          lon: Number(p.lon),
          speedMps: Number(p.speed_mps),
          heading: Number(p.heading_deg),
          edgeId: String(p.edge_id),
          type: inferVehicleType(id, p.vtype ?? p.vehicle_class ?? p.type),
          at: lastMessageAt,
        });
        break;
      }
      case "ApproachState": {
        if (typeof p.movement_id !== "string" || typeof p.occupancy !== "number" || !Number.isFinite(p.occupancy)) break;
        lastTelemetryAt = lastMessageAt;
        edges.set(String(p.movement_id), {
          occupancy: Number(p.occupancy),
          at: lastMessageAt,
        });
        break;
      }
      case "SignalChanged": {
        const iid = String(p.intersection_id);
        signalSeenAt.set(iid, {
          at: lastMessageAt,
          source: p.source == null ? "" : String(p.source),
        });
        // The arbiter emits exactly one of SignalChanged/SignalFaulted per
        // tick -- a successful command is proof this junction recovered.
        signalFaults.delete(iid);
        break;
      }
      case "EmergencyRequestUpdated": {
        const id = String(p.request_id);
        const prev = emergencyRequests.get(id);
        const state = String(p.state).toLowerCase() as EmergencyRequestState;
        const detail = p.detail == null ? "" : String(p.detail);
        const actor = p.actor == null ? "system" : String(p.actor);
        const atMs = toMs(p.updated_at);

        // client-side activity log — the backend hash chain isn't sent whole
        const timeline = pushTimelineEntry(prev?.timeline, { state, detail, actor, atMs });

        const notif = classifyEmergencyEvent(
          {
            requestId: id,
            vehicleId: String(p.vehicle_id),
            vehicleKind: String(p.vehicle_kind).toLowerCase() as EmergencyVehicleKind,
            prevState: prev?.state,
            nextState: state,
            prevDetail: prev?.detail ?? "",
            detail,
            actor,
          },
          lastMessageAt,
        );
        if (notif) pendingEvents.push(notif);

        emergencyRequests.set(id, {
          id,
          vehicleId: String(p.vehicle_id),
          vehicleKind: String(p.vehicle_kind).toLowerCase() as EmergencyVehicleKind,
          state,
          sourceEdge: String(p.source_edge),
          destinationEdge: String(p.destination_edge),
          etaS: p.eta_s == null ? undefined : Number(p.eta_s),
          greenCorridorId: p.green_corridor_id == null ? undefined : String(p.green_corridor_id),
          route: mapRoute(p.route),
          alternatives: Array.isArray(p.alternatives)
            ? (p.alternatives.map(mapRoute).filter(Boolean) as EmergencyRouteView[])
            : [],
          // corridor + live position arrive on their own event streams; carry
          // them across a request-state refresh
          corridor: prev?.corridor,
          live: prev?.live,
          timeline,
          detail: detail || undefined,
          updatedAt: msToIso(p.updated_at),
          _at: lastMessageAt,
        });
        break;
      }
      case "GreenCorridorUpdated": {
        const rid = String(p.request_id);
        const existing = emergencyRequests.get(rid);
        if (existing) {
          const next = mapCorridor(p);
          next.passedIntersections = mergePassed(
            existing.corridor?.passedIntersections,
            next.passedIntersections,
          );
          existing.corridor = next;
          existing._at = lastMessageAt;
        }
        const event = p.event == null ? "" : String(p.event);
        const notif = classifyCorridorEvent(
          {
            requestId: rid,
            corridorId: String(p.corridor_id ?? ""),
            event,
            junctionId:
              event === "junction_passed" && typeof p.detail === "string" ? p.detail : undefined,
          },
          lastMessageAt,
        );
        if (notif) pendingEvents.push(notif);
        break;
      }
      case "EmergencyVehicleUpdated": {
        const rid = String(p.request_id);
        const existing = emergencyRequests.get(rid);
        if (existing) {
          existing.live = mapVehicleLive(p);
          existing._at = lastMessageAt;
        }
        break;
      }
      case "AnomalyUpdated": {
        const id = String(p.anomaly_id);
        const prevStatus = anomalies.get(id)?.status;
        const anomaly: Anomaly = {
          id,
          source: String(p.source).toLowerCase() as AnomalySource,
          kind: String(p.anomaly_type).toLowerCase() as AnomalyKind,
          severity: String(p.severity).toLowerCase() as AnomalySeverity,
          status: String(p.status).toLowerCase() as AnomalyStatus,
          edgeId: String(p.edge_id),
          laneId: p.lane_id == null ? undefined : String(p.lane_id),
          estimatedImpact: Number(p.estimated_impact),
          startTime: msToIso(p.start_time_ms),
          expiresAt: p.expires_at_ms == null ? undefined : msToIso(p.expires_at_ms),
          detail: p.detail == null ? undefined : String(p.detail),
          operator: p.operator == null ? undefined : String(p.operator),
        };
        anomalies.set(id, { ...anomaly, _at: lastMessageAt });
        const notif = classifyAnomalyEvent(prevStatus, anomaly, lastMessageAt);
        if (notif) pendingEvents.push(notif);
        break;
      }
      case "CrewOfferUpdated": {
        // Straight to the crew store rather than into the map snapshot: an
        // offer is addressed to one driver and is their page's state, not
        // something the console's shared view of the city needs.
        useCrewStore.getState().applyOffer(p as Record<string, unknown>);
        break;
      }
      case "CrewRosterUpdated": {
        // The fleet with its simulated positions, for both maps.
        useCrewStore.getState().applyFleet(p as Record<string, unknown>);
        break;
      }
      case "CrewHospitalOptions": {
        // An ambulance at a scene, or on its way to the hospital its crew chose.
        useCrewStore.getState().applyHospital(p as Record<string, unknown>);
        break;
      }
      case "SignalFaulted": {
        const iid = String(p.intersection_id);
        const faultType = p.fault_type == null ? "" : String(p.fault_type);
        const detail = p.detail == null ? "" : String(p.detail);
        signalFaults.set(iid, { faultType, detail, at: lastMessageAt });
        pendingEvents.push(
          classifySignalFault({ intersectionId: iid, faultType, detail }, lastMessageAt),
        );
        break;
      }
      default:
        break; // SystemHeartbeat, others — ignored for the map
    }
  }

  function prune(now: number) {
    for (const [id, v] of vehicles) if (now - v.at > ENTRY_STALE_MS) vehicles.delete(id);
    for (const [id, e] of edges) if (now - e.at > ENTRY_STALE_MS) edges.delete(id);
    // keep a terminal anomaly around ~4s so its RESOLVED/CANCELLED state can
    // animate out, then forget it
    for (const [id, a] of anomalies) {
      if (a.status !== "active" && now - a._at > 4_000) anomalies.delete(id);
    }
    for (const [id, r] of emergencyRequests) {
      // Mirrors emergencyStore's isTerminalRequest — duplicated on purpose:
      // this data-layer file must not depend on a Zustand store.
      const done = r.state === "completed" || r.state === "cancelled";
      if (done && now - r._at > TERMINAL_REQUEST_TTL_MS) emergencyRequests.delete(id);
      const streamLive = now - lastMessageAt < STREAM_LIVE_MS;
      if (!done && streamLive && now - r._at > ORPHAN_REQUEST_MS) emergencyRequests.delete(id);
    }
    for (const [id, f] of signalFaults) {
      if (now - f.at > SIGNAL_FAULT_TTL_MS) signalFaults.delete(id);
    }
  }

  function buildSnapshot(): TrafficSnapshot {
    const now = Date.now();
    prune(now);
    const iso = new Date(now).toISOString();

    const vehList: Vehicle[] = [];
    for (const [id, v] of vehicles) {
      vehList.push({
        id,
        type: v.type,
        latitude: v.lat,
        longitude: v.lon,
        speed: Math.max(0, v.speedMps) * 3.6,
        heading: v.heading,
        lane: v.edgeId,
        timestamp: iso,
      });
    }

    const roadCongestion: Record<string, number> = {};
    for (const [edgeId, e] of edges) roadCongestion[edgeId] = Math.min(1, Math.max(0, e.occupancy));

    const intersections: Intersection[] = signalJunctions.map((j) => {
      const stats = junctionVehicleStats([j.lng, j.lat], vehList);
      const seen = signalSeenAt.get(j.id);
      const underControl = seen != null && now - seen.at < SIGNAL_FRESH_MS;
      const fault = signalFaults.get(j.id);
      return {
        id: j.id,
        name: shortJunctionName(j.id),
        latitude: j.lat,
        longitude: j.lng,
        ...stats,
        signalState: (underControl ? "green" : "red") as SignalState,
        preempted: underControl && seen.source === "corridor_preemption",
        fault: fault
          ? { faultType: fault.faultType, detail: fault.detail, atMs: fault.at }
          : undefined,
      };
    });

    const congestionAvg =
      Object.values(roadCongestion).reduce((s, v) => s + v, 0) /
      Math.max(1, Object.keys(roadCongestion).length);

    const incidents = [...detectorIncidents.values()];

    const anomalyList: Anomaly[] = [];
    for (const [, a] of anomalies) {
      const { _at, ...rest } = a;
      void _at;
      anomalyList.push(rest);
    }

    const emergencyRequestList: EmergencyRequest[] = [];
    for (const [, r] of emergencyRequests) {
      const { _at, ...rest } = r;
      void _at;
      emergencyRequestList.push(rest);
    }

    const summary: SystemSummary = {
      operational: status === "online" && lastTelemetryAt > 0 && now - lastTelemetryAt < 6_000,
      vehicleCount: vehList.length,
      congestion: Number.isFinite(congestionAvg) ? congestionAvg : 0,
      signalsOnline: intersections.filter((i) => i.signalState !== "red").length,
      signalsTotal: signalJunctions.length,
      lastUpdate: lastTelemetryAt > 0 ? new Date(lastTelemetryAt).toISOString() : null,
    };

    const events = pendingEvents;
    pendingEvents = [];

    return {
      timestamp: iso,
      vehicles: vehList,
      intersections,
      incidents,
      anomalies: anomalyList,
      emergencyRequests: emergencyRequestList,
      roadCongestion,
      summary,
      events,
    };
  }

  function emitSnapshot() {
    // Connection status belongs to the transport lifecycle (`onopen`,
    // `onclose`, `onerror`), not the event cadence. SUMO may legitimately be
    // quiet; an open Live socket must stay Online in that interval.
    const snap = buildSnapshot();
    for (const l of snapshotListeners) l(snap);
  }

  function connect() {
    if (stopped) return;
    setStatus(reconnectTries === 0 ? "connecting" : "reconnecting");
    try {
      ws = new WebSocket(wsUrl());
    } catch {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      reconnectTries = 0;
      lastMessageAt = 0;
      setStatus("online");
    };
    ws.onmessage = (evt) => {
      let env: Envelope;
      try {
        env = JSON.parse(evt.data as string) as Envelope;
      } catch {
        return;
      }
      if (!env || typeof env.event_type !== "string" || !env.payload || typeof env.payload !== "object" || Array.isArray(env.payload)) return;
      handleEnvelope(env);
    };
    ws.onerror = () => ws?.close();
    ws.onclose = () => {
      ws = null;
      if (!stopped) scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer != null) return;
    const delay = RECONNECT_MS[Math.min(reconnectTries, RECONNECT_MS.length - 1)];
    reconnectTries += 1;
    setStatus("reconnecting");
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  return {
    mode: "live",
    start() {
      if (!stopped) return;
      stopped = false;
      reconnectTries = 0;
      connect();
      snapshotTimer = window.setInterval(emitSnapshot, SNAPSHOT_MS);
    },
    stop() {
      stopped = true;
      if (snapshotTimer != null) window.clearInterval(snapshotTimer);
      if (reconnectTimer != null) window.clearTimeout(reconnectTimer);
      snapshotTimer = reconnectTimer = null;
      ws?.close();
      ws = null;
      vehicles.clear();
      detectorIncidents.clear();
      lastTelemetryAt = lastMessageAt = 0;
      edges.clear();
      signalSeenAt.clear();
      signalFaults.clear();
      anomalies.clear();
      emergencyRequests.clear();
      pendingEvents = [];
      setStatus("offline");
    },
    subscribe(listener) {
      snapshotListeners.add(listener);
      return () => snapshotListeners.delete(listener);
    },
    onStatus(listener) {
      statusListeners.add(listener);
      listener(status);
      return () => statusListeners.delete(listener);
    },
    sendCommand(cmd: OperatorCommand): Promise<CommandResult> {
      return postCommand(cmd);
    },
  };
}
