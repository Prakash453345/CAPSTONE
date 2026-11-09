/**
 * Browser-side stand-in for the sim-service command loop, so Demo mode answers
 * operator commands the way Live does: it takes the same `OperatorCommand`s,
 * keeps the same lifecycles (anomaly active -> resolved; call offered -> crew
 * accepts -> routing -> route ready -> green corridor -> arrived -> hospital),
 * and hands back the same normalised shapes the WebSocket provider builds from
 * the wire — including the notification events. Nothing here talks to a server.
 *
 * Illustrative, not authoritative: routing is a cost-weighted Dijkstra over the
 * demo network's geometric adjacency, and travel is constant-speed. Timings
 * mirror Live's feel (offers last 25 s, a crew that is not answered by hand
 * accepts after a few seconds).
 */

import type {
  Anomaly,
  AnomalyKind,
  AnomalySeverity,
  EmergencyRequest,
  EmergencyRequestState,
  EmergencyRouteView,
  EmergencyVehicleKind,
  GreenCorridorView,
  NotificationEvent,
} from "@/types";
import {
  edgeById,
  roadEdges,
  roadLabel,
  signalJunctions,
  type RoadEdge,
} from "@/data/network";
import {
  cumulativeLengths,
  haversineMeters,
  pointAlongPath,
  type LngLat,
} from "@/utils/geo";
import { useCrewStore } from "@/store/crewStore";
import { CommandError, type CommandResult, type OperatorCommand } from "@/services/traffic/commands";
import {
  classifyAnomalyEvent,
  classifyCorridorEvent,
  classifyEmergencyEvent,
} from "@/services/traffic/notifications";
import { pushTimelineEntry } from "@/services/traffic/wsMappers";

const OFFER_TIMEOUT_S = 25;
/** A crew nobody answers for accepts after this long, as a stand-in driver. */
const AUTO_ACCEPT_S = 6;
const ROUTING_S = 1.5;
/** An operator who does not start the corridor still gets one. */
const AUTO_CORRIDOR_S = 6;
const SCENE_CHOICE_S = 25;
const KEEP_FINISHED_MS = 90_000;
const JUNCTION_SNAP_M = 40;
const SIGNAL_DELAY_S = 6;
const ACTOR = "operator:demo";

const SPEED_MPS = 10;
const CORRIDOR_SPEED_MPS = 15;

const IMPACT: Record<AnomalySeverity, number> = { low: 0.25, medium: 0.5, high: 0.8, blocked: 1 };
/** Seconds of detour a route will accept to stay off an edge of this severity. */
const PENALTY_S: Record<AnomalySeverity, number> = { low: 30, medium: 90, high: 240, blocked: 1800 };
const RESPONDERS: Partial<Record<AnomalyKind, EmergencyVehicleKind[]>> = {
  accident: ["police", "ambulance", "fire_truck"],
  fire: ["fire_truck", "police"],
  vehicle_breakdown: ["police"],
  lane_blockage: ["police"],
  road_obstruction: ["police"],
  stalled_vehicle: ["police"],
};

const HOSPITAL_NAMES = ["City General Hospital", "Trauma Centre", "Community Hospital"];

let seq = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

// ---------------------------------------------------------------- routing

interface Leg {
  edge: RoadEdge;
  reversed: boolean;
}

const legPath = (l: Leg): LngLat[] => (l.reversed ? [...l.edge.path].reverse() : l.edge.path);
const legExit = (l: Leg): LngLat => (l.reversed ? l.edge.path[0]! : l.edge.path[l.edge.path.length - 1]!);

/** Edges whose first or last point sits near a given point, bucketed by ~55 m. */
const BUCKET = 2000;
const buckets = new Map<string, { edge: RoadEdge; atStart: boolean }[]>();
const bucketKey = (p: LngLat, dx = 0, dy = 0) => `${Math.round(p[0] * BUCKET) + dx},${Math.round(p[1] * BUCKET) + dy}`;
for (const edge of roadEdges) {
  for (const atStart of [true, false]) {
    const p = atStart ? edge.path[0]! : edge.path[edge.path.length - 1]!;
    const k = bucketKey(p);
    const list = buckets.get(k);
    if (list) list.push({ edge, atStart });
    else buckets.set(k, [{ edge, atStart }]);
  }
}

function successors(leg: Leg): Leg[] {
  const exit = legExit(leg);
  const out: Leg[] = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      for (const { edge, atStart } of buckets.get(bucketKey(exit, dx, dy)) ?? []) {
        if (edge.id === leg.edge.id) continue;
        const p = atStart ? edge.path[0]! : edge.path[edge.path.length - 1]!;
        if (haversineMeters(exit, p) < 45) out.push({ edge, reversed: !atStart });
      }
    }
  }
  return out;
}

class MinHeap {
  private a: [number, string][] = [];
  get size() {
    return this.a.length;
  }
  push(cost: number, key: string) {
    const a = this.a;
    a.push([cost, key]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p]![0] <= a[i]![0]) break;
      [a[p], a[i]] = [a[i]!, a[p]!];
      i = p;
    }
  }
  pop(): [number, string] {
    const a = this.a;
    const top = a[0]!;
    const last = a.pop()!;
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && a[l]![0] < a[m]![0]) m = l;
        if (r < a.length && a[r]![0] < a[m]![0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i]!, a[m]!];
        i = m;
      }
    }
    return top;
  }
}

const legKey = (l: Leg) => `${l.edge.id}|${l.reversed ? 1 : 0}`;
const legSeconds = (l: Leg, penalty: Map<string, number>) =>
  l.edge.lengthM / Math.max(3, l.edge.speedLimitMps) + (penalty.get(l.edge.id) ?? 0);

/** Cheapest leg chain from `fromEdge` to `toEdge`. `startReversed` pins the
 *  starting direction (a vehicle already driving); otherwise both are tried. */
export function planLegs(
  fromEdge: string,
  toEdge: string,
  penalty: Map<string, number>,
  startReversed?: boolean,
): Leg[] | null {
  const from = edgeById.get(fromEdge);
  const to = edgeById.get(toEdge);
  if (!from || !to) return null;
  const best = new Map<string, number>();
  const prev = new Map<string, string>();
  const byKey = new Map<string, Leg>();
  const heap = new MinHeap();
  for (const reversed of startReversed === undefined ? [false, true] : [startReversed]) {
    const l: Leg = { edge: from, reversed };
    const k = legKey(l);
    byKey.set(k, l);
    best.set(k, legSeconds(l, penalty));
    heap.push(best.get(k)!, k);
  }
  while (heap.size) {
    const [cost, k] = heap.pop();
    if (cost > (best.get(k) ?? Infinity)) continue;
    const leg = byKey.get(k)!;
    if (leg.edge.id === toEdge) {
      const chain: Leg[] = [];
      for (let cur: string | undefined = k; cur; cur = prev.get(cur)) chain.push(byKey.get(cur)!);
      return chain.reverse();
    }
    for (const nxt of successors(leg)) {
      const nk = legKey(nxt);
      const c = cost + legSeconds(nxt, penalty);
      if (c < (best.get(nk) ?? Infinity)) {
        best.set(nk, c);
        prev.set(nk, k);
        byKey.set(nk, nxt);
        heap.push(c, nk);
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------- engine state

interface Unit {
  id: string;
  kind: EmergencyVehicleKind;
  callSign: string;
  edgeId: string;
  at: LngLat;
  busy: boolean;
}

interface Call {
  requestId: string;
  kind: EmergencyVehicleKind;
  sceneEdge: string;
  asked: string[];
  offer?: { offerId: string; unitId: string; expiresAtMs: number; autoAcceptAtMs: number };
}

interface Hospital {
  facilityId: string;
  name: string;
  edgeId: string;
  at: LngLat;
}

type Phase = "routing" | "ready" | "driving" | "at_scene" | "done";

interface Mission {
  req: EmergencyRequest;
  unit: Unit;
  phase: Phase;
  phaseAtMs: number;
  legs: Leg[];
  coords: LngLat[];
  cum: number[];
  legStart: number[];
  distM: number;
  speedMps: number;
  /** Anomaly edges this mission already knows about, so one is reported once. */
  knownBad: Set<string>;
  corridorOn: boolean;
  passed: Set<string>;
  /** Signalised junctions on the route with the distance along it. */
  junctions: { id: string; atM: number }[];
  hospitalLeg: boolean;
  chosenHospital: string;
  recommendedHospital: string;
  hospitals: Hospital[];
  finishedAtMs: number;
  /** The opening demo mission: skips the routing and corridor waits. */
  underway?: boolean;
}

export interface DemoTick {
  anomalies: Anomaly[];
  requests: EmergencyRequest[];
  events: NotificationEvent[];
}

export interface DemoEngine {
  /** Brings the demo fleet onto the crew store. */
  start(): void;
  /** Puts Ambulance 1 on a long call, so the demo opens with a mission
   *  under way (the crew page and the emergency map have something to follow). */
  startDemoMission(): void;
  handle(cmd: OperatorCommand): CommandResult;
  tick(): DemoTick;
  /** 0..1: share of normal speed left on this edge because of anomalies. */
  speedFactor(edgeId: string): number;
  /** 0..1 congestion an active anomaly forces onto this edge. */
  congestion(edgeId: string): number;
}

const FLEET: [string, EmergencyVehicleKind, string][] = [
  ["amb-01", "ambulance", "Ambulance 1"],
  ["amb-02", "ambulance", "Ambulance 2"],
  ["pol-01", "police", "Police 1"],
  ["pol-02", "police", "Police 2"],
  ["fire-01", "fire_truck", "Fire 1"],
];

const mid = (e: RoadEdge): LngLat => e.path[Math.floor(e.path.length / 2)]!;

export function createDemoEngine(now: () => number = Date.now): DemoEngine {
  const anomalies = new Map<string, Anomaly & { endedAtMs?: number }>();
  const calls = new Map<string, Call>();
  const missions = new Map<string, Mission>();
  const hospitals: Hospital[] = HOSPITAL_NAMES.map((name, i) => {
    const e = roadEdges[Math.floor((roadEdges.length * (i + 1)) / (HOSPITAL_NAMES.length + 1))]!;
    return { facilityId: `hosp-${i + 1}`, name, edgeId: e.id, at: mid(e) };
  });
  const units: Unit[] = FLEET.map(([id, kind, callSign], i) => {
    const e = roadEdges[(i * 7) % roadEdges.length]!;
    return { id, kind, callSign, edgeId: e.id, at: mid(e), busy: false };
  });
  const events: NotificationEvent[] = [];
  let lastTickMs = now();
  let lastFleetMs = 0;
  let fleetDirty = true;

  // ---- helpers ------------------------------------------------------------

  const penalties = () => {
    const m = new Map<string, number>();
    for (const a of anomalies.values()) {
      if (a.status === "active") m.set(a.edgeId, Math.max(m.get(a.edgeId) ?? 0, PENALTY_S[a.severity]));
    }
    return m;
  };

  function publishFleet(force = false) {
    const t = now();
    if (!force && !fleetDirty && t - lastFleetMs < 1000) return;
    if (!force && !fleetDirty && !units.some((u) => u.busy)) return;
    lastFleetMs = t;
    fleetDirty = false;
    useCrewStore.getState().applyFleet({
      units: units.map((u) => ({
        unit_id: u.id,
        kind: u.kind,
        call_sign: u.callSign,
        on_duty: true,
        busy: u.busy,
        edge_id: u.edgeId,
        lat: u.at[1],
        lon: u.at[0],
      })),
    });
  }

  function emit(e: NotificationEvent | null) {
    if (e) events.push(e);
  }

  function routeView(legs: Leg[], coords: LngLat[], cum: number[], extra?: Partial<EmergencyRouteView>): EmergencyRouteView {
    const pen = penalties();
    const distance = cum[cum.length - 1] ?? 0;
    const travel = legs.reduce((s, l) => s + l.edge.lengthM / Math.max(3, l.edge.speedLimitMps), 0);
    const signalised = signalsAlong(coords, cum).map((j) => j.id);
    const avoidedEdges = [...pen.keys()].filter((e) => !legs.some((l) => l.edge.id === e));
    const forced = legs.filter((l) => (pen.get(l.edge.id) ?? 0) >= PENALTY_S.blocked).map((l) => l.edge.id);
    const signalDelay = signalised.length * SIGNAL_DELAY_S;
    const anomalyCost = legs.reduce((s, l) => s + (pen.get(l.edge.id) ?? 0), 0);
    const disruption = Math.round((distance / 400) * 100) / 100;
    return {
      edges: legs.map((l) => l.edge.id),
      rank: 0,
      totalDistanceM: Math.round(distance),
      totalTravelTimeS: Math.round(travel),
      etaS: Math.round(distance / SPEED_MPS + signalDelay),
      nIntersections: Math.max(0, legs.length - 1),
      signalisedIntersections: signalised,
      congestedSegments: [],
      anomalousSegmentsAvoided: avoidedEdges,
      forcedThrough: forced,
      reliable: forced.length === 0,
      cost: {
        travelTimeS: Math.round(travel * 10) / 10,
        congestion: 0.2,
        anomaly: anomalyCost,
        signalDelayS: signalDelay,
        disruption,
        reliability: forced.length ? 1 : 0.1,
        score: Math.round((travel / 60 + 0.12 + signalDelay * 0.4 + anomalyCost / 60 + disruption) * 10) / 10,
      },
      weightsUsed: {
        travel_time_weight: 1,
        congestion_weight: 0.6,
        anomaly_weight: 1,
        signal_delay_weight: 0.4,
        disruption_weight: 0.5,
        reliability_weight: 0.3,
      },
      ...extra,
    };
  }

  function signalsAlong(coords: LngLat[], cum: number[]): { id: string; atM: number }[] {
    const out: { id: string; atM: number }[] = [];
    for (const j of signalJunctions) {
      const p: LngLat = [j.lng, j.lat];
      for (let i = 0; i < coords.length; i++) {
        if (haversineMeters(coords[i]!, p) < JUNCTION_SNAP_M) {
          out.push({ id: j.id, atM: cum[i]! });
          break;
        }
      }
    }
    return out.sort((a, b) => a.atM - b.atM);
  }

  function geometry(legs: Leg[]) {
    const coords: LngLat[] = [];
    const legStart: number[] = [];
    legs.forEach((l, i) => {
      legStart.push(coords.length);
      coords.push(...(i === 0 ? legPath(l) : legPath(l).slice(1)));
    });
    return { coords, cum: cumulativeLengths(coords), legStart };
  }

  function setState(
    m: Mission,
    state: EmergencyRequestState,
    detail: string,
    actor = "system",
    patch: Partial<EmergencyRequest> = {},
  ) {
    const prev = m.req;
    const t = now();
    emit(
      classifyEmergencyEvent(
        {
          requestId: prev.id,
          vehicleId: prev.vehicleId,
          vehicleKind: prev.vehicleKind,
          prevState: prev.state,
          nextState: state,
          prevDetail: prev.detail ?? "",
          detail,
          actor,
        },
        t,
      ),
    );
    m.req = {
      ...prev,
      ...patch,
      state,
      detail: detail || undefined,
      timeline: pushTimelineEntry(prev.timeline, { state, detail, actor, atMs: t }),
      updatedAt: new Date(t).toISOString(),
    };
  }

  function startPhaseRouting(m: Mission) {
    m.phase = "routing";
    m.phaseAtMs = now();
    setState(m, "routing", "Planning the fastest safe route");
  }

  function applyPlan(m: Mission, legs: Leg[], distOffset = 0) {
    const g = geometry(legs);
    m.legs = legs;
    m.coords = g.coords;
    m.cum = g.cum;
    m.legStart = g.legStart;
    m.distM = distOffset;
    m.junctions = signalsAlong(g.coords, g.cum);
    for (const id of m.passed) m.junctions = m.junctions.filter((j) => j.id !== id);
    const view = routeView(legs, g.coords, g.cum);
    m.req = { ...m.req, route: view, etaS: view.etaS, destinationEdge: legs[legs.length - 1]!.edge.id };
  }

  function alternativeFor(m: Mission): EmergencyRouteView[] {
    const first = m.legs.map((l) => l.edge.id);
    const pen = penalties();
    for (const id of first.slice(1, -1)) pen.set(id, (pen.get(id) ?? 0) + 120);
    const alt = planLegs(m.req.sourceEdge, m.req.destinationEdge, pen);
    if (!alt || alt.map((l) => l.edge.id).join() === first.join()) return [];
    const g = geometry(alt);
    return [routeView(alt, g.coords, g.cum, { rank: 1 })];
  }

  function corridorFor(m: Mission, status: GreenCorridorView["status"]): GreenCorridorView {
    const t = now();
    const startS = (m.distM / CORRIDOR_SPEED_MPS);
    return {
      corridorId: `cor-${m.req.id}`,
      status,
      reservations: m.junctions.map((j, i) => ({
        intersectionId: j.id,
        movements: ["through"],
        openAtMs: Math.round(t + (j.atM / CORRIDOR_SPEED_MPS - startS - 8) * 1000),
        closeAtMs: Math.round(t + (j.atM / CORRIDOR_SPEED_MPS - startS + 6) * 1000),
        order: i,
      })),
      passedIntersections: [...m.passed],
      peakConcurrency: Math.min(3, m.junctions.length),
    };
  }

  function activateCorridor(m: Mission, actor: string) {
    m.corridorOn = true;
    m.speedMps = CORRIDOR_SPEED_MPS;
    m.phase = "driving";
    m.phaseAtMs = now();
    const corridor = corridorFor(m, "active");
    emit(classifyCorridorEvent({ requestId: m.req.id, corridorId: corridor.corridorId, event: "activated" }, now()));
    setState(m, "green_corridor_active", "Signals ahead are held green", actor, {
      corridor,
      greenCorridorId: corridor.corridorId,
    });
  }

  function depart(m: Mission, actor: string) {
    m.phase = "driving";
    m.phaseAtMs = now();
    m.speedMps = SPEED_MPS;
    setState(m, "in_transit", "En route", actor);
  }

  function freeUnit(m: Mission) {
    m.unit.busy = false;
    fleetDirty = true;
  }

  function finish(m: Mission) {
    m.phase = "done";
    m.finishedAtMs = now();
    const corridor = m.req.corridor ? { ...m.req.corridor, status: "completed" as const } : undefined;
    setState(m, "completed", "Arrived", "system", {
      corridor,
      live: { ...m.req.live!, speedMps: 0, etaS: 0, routeProgress: 1, status: "arrived" },
    });
    freeUnit(m);
  }

  function hospitalOptions(m: Mission) {
    const pen = penalties();
    return m.hospitals
      .map((h) => {
        const legs = planLegs(m.req.destinationEdge, h.edgeId, pen);
        const g = legs ? geometry(legs) : null;
        const etaS = g ? Math.round((g.cum[g.cum.length - 1] ?? 0) / SPEED_MPS) : 9999;
        return { ...h, etaS };
      })
      .sort((a, b) => a.etaS - b.etaS);
  }

  function publishHospital(m: Mission, state: "at_scene" | "to_hospital" | "done", sceneEdge: string) {
    useCrewStore.getState().applyHospital({
      unit_id: m.unit.id,
      request_id: m.req.id,
      scene_edge: sceneEdge,
      state,
      recommended_id: m.recommendedHospital,
      chosen_id: m.chosenHospital,
      options: hospitalOptions(m).map((o) => ({
        facility_id: o.facilityId,
        name: o.name,
        edge_id: o.edgeId,
        eta_s: o.etaS,
        lat: o.at[1],
        lon: o.at[0],
      })),
    });
  }

  function goToHospital(m: Mission, facilityId: string, sceneEdge: string) {
    const h = m.hospitals.find((x) => x.facilityId === facilityId);
    if (!h) return;
    const cur = currentLeg(m);
    const legs = planLegs(cur.edge.id, h.edgeId, penalties(), cur.reversed);
    m.chosenHospital = h.facilityId;
    if (!legs) {
      publishHospital(m, "at_scene", sceneEdge);
      return;
    }
    m.hospitalLeg = true;
    m.passed.clear();
    applyPlan(m, legs, offsetInLeg(m));
    m.phase = "driving";
    m.speedMps = m.corridorOn ? CORRIDOR_SPEED_MPS : SPEED_MPS;
    if (m.corridorOn) m.req = { ...m.req, corridor: corridorFor(m, "active") };
    setState(m, m.corridorOn ? "green_corridor_active" : "in_transit", `Taking patient to ${h.name}`, "system");
    publishHospital(m, "to_hospital", sceneEdge);
  }

  function legIndex(m: Mission) {
    let i = 0;
    for (let k = 0; k < m.legStart.length; k++) if (m.cum[m.legStart[k]!]! <= m.distM) i = k;
    return i;
  }
  const currentLeg = (m: Mission) => m.legs[legIndex(m)]!;
  const offsetInLeg = (m: Mission) => m.distM - m.cum[m.legStart[legIndex(m)]!]!;

  function startMission(call: Call, unit: Unit) {
    unit.busy = true;
    fleetDirty = true;
    const t = now();
    const legs = planLegs(unit.edgeId, call.sceneEdge, penalties());
    const blank: EmergencyRequest = {
      id: call.requestId,
      vehicleId: unit.id,
      vehicleKind: unit.kind,
      state: "created",
      sourceEdge: unit.edgeId,
      destinationEdge: call.sceneEdge,
      alternatives: [],
      timeline: [],
      updatedAt: new Date(t).toISOString(),
    };
    const m: Mission = {
      req: blank,
      unit,
      phase: "routing",
      phaseAtMs: t,
      legs: [],
      coords: [],
      cum: [],
      legStart: [],
      distM: 0,
      speedMps: SPEED_MPS,
      knownBad: new Set([...penalties().keys()]),
      corridorOn: false,
      passed: new Set(),
      junctions: [],
      hospitalLeg: false,
      chosenHospital: "",
      recommendedHospital: "",
      hospitals,
      finishedAtMs: 0,
    };
    missions.set(call.requestId, m);
    setState(m, "created", "Crew accepted the call");
    if (!legs) {
      setState(m, "cancelled", "no route could be found to the scene");
      m.phase = "done";
      m.finishedAtMs = t;
      freeUnit(m);
      return;
    }
    applyPlan(m, legs);
    startPhaseRouting(m);
  }

  // ---- calls & offers -----------------------------------------------------

  function offerNext(call: Call) {
    const scene = edgeById.get(call.sceneEdge);
    const sceneAt = scene ? mid(scene) : null;
    const candidates = units
      .filter((u) => u.kind === call.kind && !u.busy && !call.asked.includes(u.id))
      .sort((a, b) => (sceneAt ? haversineMeters(a.at, sceneAt) - haversineMeters(b.at, sceneAt) : 0));
    const unit = candidates[0];
    if (!unit) {
      calls.delete(call.requestId);
      useCrewStore.getState().applyOffer({
        incident_id: call.requestId,
        kind: call.kind,
        state: "exhausted",
        unit_id: "",
        asked: call.asked,
      });
      return;
    }
    call.asked.push(unit.id);
    const t = now();
    const legs = planLegs(unit.edgeId, call.sceneEdge, penalties());
    const etaS = legs ? Math.round((geometry(legs).cum.at(-1) ?? 0) / SPEED_MPS) : 0;
    call.offer = {
      offerId: nextId("offer"),
      unitId: unit.id,
      expiresAtMs: t + OFFER_TIMEOUT_S * 1000,
      autoAcceptAtMs: t + AUTO_ACCEPT_S * 1000,
    };
    useCrewStore.getState().applyOffer({
      offer_id: call.offer.offerId,
      incident_id: call.requestId,
      unit_id: unit.id,
      kind: call.kind,
      edge_id: call.sceneEdge,
      eta_s: etaS,
      state: "offered",
      asked: call.asked,
    });
  }

  function settleOffer(call: Call, state: "accepted" | "declined" | "expired") {
    const offer = call.offer;
    if (!offer) return;
    call.offer = undefined;
    useCrewStore.getState().applyOffer({
      offer_id: offer.offerId,
      incident_id: call.requestId,
      unit_id: offer.unitId,
      kind: call.kind,
      edge_id: call.sceneEdge,
      state,
      asked: call.asked,
    });
    if (state === "accepted") {
      calls.delete(call.requestId);
      const unit = units.find((u) => u.id === offer.unitId);
      if (unit) startMission(call, unit);
    } else {
      offerNext(call);
    }
  }

  function openCall(requestId: string, kind: EmergencyVehicleKind, sceneEdge: string) {
    const call: Call = { requestId, kind, sceneEdge, asked: [] };
    calls.set(requestId, call);
    offerNext(call);
  }

  // ---- command handlers ---------------------------------------------------

  const text = (v: unknown) => (typeof v === "string" ? v : "");

  function createAnomaly(p: Record<string, unknown>) {
    const id = text(p.anomaly_id) || nextId("anom");
    const edgeId = text(p.edge_id);
    if (!edgeById.has(edgeId)) throw new CommandError(422, "That road is not on the demo network.");
    const kind = text(p.anomaly_type).toLowerCase() as AnomalyKind;
    const severity = (text(p.severity).toLowerCase() || "medium") as AnomalySeverity;
    if (!(severity in IMPACT)) throw new CommandError(422, `Unknown severity ${text(p.severity)}.`);
    const t = now();
    const duration = typeof p.duration_s === "number" ? p.duration_s : null;
    const anomaly: Anomaly = {
      id,
      source: "operator",
      kind,
      severity,
      status: "active",
      edgeId,
      estimatedImpact: IMPACT[severity],
      startTime: new Date(t).toISOString(),
      expiresAt: duration == null ? undefined : new Date(t + duration * 1000).toISOString(),
      operator: ACTOR,
    };
    anomalies.set(id, anomaly);
    emit(classifyAnomalyEvent(undefined, anomaly, t));
    // Alerting the authorities: a call goes out for each responder this kind sends.
    for (const responder of RESPONDERS[kind] ?? []) openCall(nextId("req"), responder, edgeId);
  }

  function clearAnomaly(p: Record<string, unknown>) {
    const a = anomalies.get(text(p.anomaly_id));
    if (!a) throw new CommandError(404, "That anomaly is no longer on the network.");
    if (a.status !== "active") return;
    const resolution = text(p.resolution) === "CANCELLED" ? "cancelled" : "resolved";
    const next = { ...a, status: resolution as Anomaly["status"], endedAtMs: now() };
    anomalies.set(a.id, next);
    emit(classifyAnomalyEvent("active", next, now()));
  }

  function createEmergency(p: Record<string, unknown>) {
    const requestId = text(p.request_id) || nextId("req");
    const kind = text(p.vehicle_kind).toLowerCase() as EmergencyVehicleKind;
    const edge = text(p.destination_edge) || text(p.source_edge);
    if (!edgeById.has(edge)) throw new CommandError(422, "That location is not on the demo network.");
    if (!units.some((u) => u.kind === kind)) throw new CommandError(422, `No ${kind} units in the demo fleet.`);
    openCall(requestId, kind, edge);
  }

  function emergencyCommand(p: Record<string, unknown>) {
    const id = text(p.request_id);
    const action = text(p.action).toUpperCase();
    const call = calls.get(id);
    if (call) {
      if (action !== "CANCEL") throw new CommandError(409, "Still finding a crew for this call.");
      const unitId = call.offer?.unitId ?? "";
      calls.delete(id);
      useCrewStore.getState().applyOffer({
        offer_id: call.offer?.offerId ?? "",
        incident_id: id,
        unit_id: unitId,
        kind: call.kind,
        state: "withdrawn",
        asked: call.asked,
      });
      return;
    }
    const m = missions.get(id);
    if (!m) throw new CommandError(404, "That request is no longer active.");
    if (m.phase === "done") throw new CommandError(409, "That request has already finished.");
    const detail = text(p.reason);
    switch (action) {
      case "CANCEL":
        m.phase = "done";
        m.finishedAtMs = now();
        setState(m, "cancelled", "Stood down by operator", ACTOR, {
          corridor: m.req.corridor ? { ...m.req.corridor, status: "cancelled" } : undefined,
        });
        freeUnit(m);
        if (m.hospitalLeg) publishHospital(m, "done", m.req.sourceEdge);
        break;
      case "ACTIVATE_CORRIDOR":
        if (m.req.state !== "route_ready") throw new CommandError(409, "A corridor can only start from a ready route.");
        activateCorridor(m, ACTOR);
        break;
      case "DEPART":
        if (m.req.state !== "route_ready") throw new CommandError(409, "That request has already set off.");
        depart(m, ACTOR);
        break;
      case "RECALCULATE":
      case "REROUTE": {
        if (m.phase !== "ready" && m.phase !== "driving") throw new CommandError(409, "Nothing to re-plan right now.");
        const cur = m.phase === "driving" ? currentLeg(m) : null;
        const from = cur ? cur.edge.id : m.req.sourceEdge;
        const legs = planLegs(from, m.req.destinationEdge, penalties(), cur?.reversed);
        if (!legs) throw new CommandError(409, "No route could be found from here.");
        applyPlan(m, legs, cur ? offsetInLeg(m) : 0);
        if (m.phase === "ready") m.req = { ...m.req, alternatives: alternativeFor(m) };
        if (m.req.corridor) m.req = { ...m.req, corridor: corridorFor(m, "active") };
        setState(m, m.req.state, detail || "Route re-planned", ACTOR);
        break;
      }
      default:
        throw new CommandError(422, `Unknown action ${action}.`);
    }
  }

  function crewOfferResponse(p: Record<string, unknown>) {
    const offerId = text(p.offer_id);
    const call = [...calls.values()].find((c) => c.offer?.offerId === offerId);
    if (!call?.offer) throw new CommandError(409, "That call is no longer being offered.");
    settleOffer(call, p.accept === true ? "accepted" : "declined");
  }

  function crewHospitalChoice(p: Record<string, unknown>) {
    const unitId = text(p.unit_id);
    const m = [...missions.values()].find((x) => x.unit.id === unitId && x.phase !== "done");
    if (!m) throw new CommandError(404, "No active patient run for that unit.");
    const facilityId = text(p.facility_id);
    if (!m.hospitals.some((h) => h.facilityId === facilityId)) throw new CommandError(422, "Unknown hospital.");
    if (m.phase === "at_scene" || m.hospitalLeg) goToHospital(m, facilityId, sceneOf(m));
    else m.chosenHospital = facilityId;
  }

  const sceneEdges = new Map<string, string>();
  const sceneOf = (m: Mission) => sceneEdges.get(m.req.id) ?? m.req.destinationEdge;

  // ---- tick ---------------------------------------------------------------

  function advance(m: Mission, dt: number, t: number) {
    if (m.phase === "routing" && t - m.phaseAtMs >= ROUTING_S * 1000) {
      m.phase = "ready";
      m.phaseAtMs = t;
      m.req = { ...m.req, alternatives: alternativeFor(m) };
      setState(m, "route_ready", "Route ready");
      if (m.unit.kind === "ambulance") {
        m.recommendedHospital = hospitalOptions(m)[0]!.facilityId;
        m.chosenHospital = m.recommendedHospital;
      }
      if (m.underway) activateCorridor(m, "system");
      return;
    }
    if (m.phase === "ready" && t - m.phaseAtMs >= AUTO_CORRIDOR_S * 1000) {
      activateCorridor(m, "system");
      return;
    }
    if (m.phase === "at_scene" && t - m.phaseAtMs >= SCENE_CHOICE_S * 1000) {
      goToHospital(m, m.chosenHospital || m.recommendedHospital, sceneOf(m));
      return;
    }
    if (m.phase !== "driving") return;

    const total = m.cum[m.cum.length - 1] ?? 0;
    m.distM = Math.min(total, m.distM + m.speedMps * dt);
    const p = pointAlongPath(m.coords, m.cum, m.distM);
    const leg = currentLeg(m);
    m.unit.at = [p.lng, p.lat];
    m.unit.edgeId = leg.edge.id;
    fleetDirty = true;

    for (const j of m.junctions) {
      if (m.distM >= j.atM && !m.passed.has(j.id)) {
        m.passed.add(j.id);
        if (m.corridorOn) {
          emit(classifyCorridorEvent({ requestId: m.req.id, corridorId: `cor-${m.req.id}`, event: "junction_passed", junctionId: j.id }, t));
        }
      }
    }
    const remaining = total - m.distM;
    m.req = {
      ...m.req,
      etaS: Math.round(remaining / m.speedMps),
      corridor: m.req.corridor ? corridorFor(m, "active") : undefined,
      live: {
        lat: p.lat,
        lon: p.lng,
        edgeId: leg.edge.id,
        speedMps: m.speedMps,
        etaS: Math.round(remaining / m.speedMps),
        routeProgress: total ? m.distM / total : 1,
        status: "en_route",
      },
      updatedAt: new Date(t).toISOString(),
    };

    if (m.distM >= total - 0.5) {
      if (m.unit.kind === "ambulance" && !m.hospitalLeg) {
        const scene = m.req.destinationEdge;
        sceneEdges.set(m.req.id, scene);
        m.phase = "at_scene";
        m.phaseAtMs = t;
        m.req = { ...m.req, live: { ...m.req.live!, speedMps: 0, etaS: 0, routeProgress: 1, status: "arrived" } };
        setState(m, m.req.state, "At the scene — choosing a hospital", "system");
        publishHospital(m, "at_scene", scene);
      } else {
        if (m.hospitalLeg) publishHospital(m, "done", sceneOf(m));
        finish(m);
      }
      return;
    }
    watchRoute(m);
  }

  /** When a new serious anomaly lands ahead on the route, reroute or hold. */
  function watchRoute(m: Mission) {
    const ahead = new Set(m.legs.slice(legIndex(m) + 1).map((l) => l.edge.id));
    const bad = [...anomalies.values()].find(
      (a) => a.status === "active" && ahead.has(a.edgeId) && IMPACT[a.severity] >= IMPACT.high && !m.knownBad.has(a.edgeId),
    );
    if (!bad) return;
    m.knownBad.add(bad.edgeId);
    const what = `${bad.severity} ${bad.kind.replace(/_/g, " ")} on ${roadLabel(bad.edgeId)}`;
    const cur = currentLeg(m);
    const legs = planLegs(cur.edge.id, m.req.destinationEdge, penalties(), cur.reversed);
    if (legs && !legs.some((l) => l.edge.id === bad.edgeId)) {
      applyPlan(m, legs, offsetInLeg(m));
      setState(m, m.req.state, `auto-reroute — avoiding ${what}`);
    } else {
      setState(m, m.req.state, `reroute held: ${what}`);
    }
  }

  return {
    start() {
      publishFleet(true);
    },
    startDemoMission() {
      const unit = units.find((u) => u.id === "amb-01");
      if (!unit || unit.busy) return;
      // A scene far enough away that the run lasts a few minutes: the first
      // sampled road 2.5 km or more away, else the farthest one there is.
      const stride = Math.max(1, Math.floor(roadEdges.length / 80));
      let best: { edge: RoadEdge; m: number } | null = null;
      for (let i = 0; i < roadEdges.length; i += stride) {
        const edge = roadEdges[i]!;
        if (edge.id === unit.edgeId) continue;
        const legs = planLegs(unit.edgeId, edge.id, new Map());
        const m = legs ? (geometry(legs).cum.at(-1) ?? 0) : 0;
        if (!best || m > best.m) best = { edge, m };
        if (m >= 2500) break;
      }
      if (!best) return;
      startMission({ requestId: "demo-amb-01", kind: "ambulance", sceneEdge: best.edge.id, asked: [unit.id] }, unit);
      const m = missions.get("demo-amb-01");
      if (m) {
        m.underway = true;
        m.phaseAtMs -= ROUTING_S * 1000;
      }
    },
    handle(cmd) {
      const p = cmd.payload;
      switch (cmd.event_type) {
        case "AnomalyCreateRequested":
          createAnomaly(p);
          break;
        case "AnomalyClearRequested":
          clearAnomaly(p);
          break;
        case "EmergencyRequestCreated":
          createEmergency(p);
          break;
        case "EmergencyCommand":
          emergencyCommand(p);
          break;
        case "CrewOfferResponse":
          crewOfferResponse(p);
          break;
        case "CrewHospitalChoice":
          crewHospitalChoice(p);
          break;
        default:
          throw new CommandError(422, `${cmd.event_type} is not supported in Demo.`);
      }
      publishFleet();
      return { published: true, topic: "commands.operator", message_id: nextId("demo") };
    },
    tick() {
      const t = now();
      const dt = Math.min(5, Math.max(0, (t - lastTickMs) / 1000));
      lastTickMs = t;

      for (const a of anomalies.values()) {
        if (a.status === "active" && a.expiresAt && Date.parse(a.expiresAt) <= t) {
          const next = { ...a, status: "resolved" as const, endedAtMs: t };
          anomalies.set(a.id, next);
                emit(classifyAnomalyEvent("active", next, t));
        } else if (a.endedAtMs && t - a.endedAtMs > 5 * 60_000) {
          anomalies.delete(a.id);
        }
      }
      for (const call of [...calls.values()]) {
        if (!call.offer) continue;
        if (t >= call.offer.expiresAtMs) settleOffer(call, "expired");
        else if (t >= call.offer.autoAcceptAtMs) settleOffer(call, "accepted");
      }
      for (const [id, m] of missions) {
        advance(m, dt, t);
        if (m.phase === "done" && t - m.finishedAtMs > KEEP_FINISHED_MS) missions.delete(id);
      }
      publishFleet();
      const out = events.splice(0, events.length);
      return {
        anomalies: [...anomalies.values()].map(({ endedAtMs: _e, ...a }) => a),
        requests: [...missions.values()].map((m) => m.req),
        events: out,
      };
    },
    speedFactor(edgeId) {
      let f = 1;
      for (const a of anomalies.values()) if (a.status === "active" && a.edgeId === edgeId) f = Math.min(f, 1 - a.estimatedImpact * 0.9);
      return f;
    },
    congestion(edgeId) {
      let c = 0;
      for (const a of anomalies.values()) if (a.status === "active" && a.edgeId === edgeId) c = Math.max(c, a.estimatedImpact);
      return c;
    },
  };
}
