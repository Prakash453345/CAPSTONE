import type {
  Incident,
  Intersection,
  SignalState,
  Vehicle,
  VehicleType,
} from "@/types";
import {
  edgeAdjacency,
  edgeById,
  roadEdges,
  shortJunctionName,
  signalJunctions,
  type RoadEdge,
} from "@/data/network";
import { haversineMeters, pointAlongPath, type LngLat } from "@/utils/geo";
import { setDemoCommandHandler } from "@/services/traffic/commands";
import { createDemoEngine } from "@/services/traffic/demoEngine";
import { mulberry32, pick } from "@/utils/rng";
import { junctionVehicleStats } from "@/services/traffic/intersectionStats";
import type {
  ProviderStatus,
  TrafficDataProvider,
  TrafficSnapshot,
} from "@/services/traffic/types";

const TICK_MS = 1000;
const VEHICLE_COUNT = 90;
const SIGNAL_CYCLE_S = 60;
const GREEN_S = 32;
const YELLOW_S = 4;
/** Metres of road one vehicle "occupies" when estimating congestion. */
const SLOT_M = 26;
const VEHICLE_TYPES: { type: VehicleType; weight: number; speed: number }[] = [
  { type: "car", weight: 0.52, speed: 12 },
  { type: "motorcycle", weight: 0.22, speed: 14 },
  { type: "truck", weight: 0.12, speed: 9 },
  { type: "bus", weight: 0.14, speed: 8 },
];

interface Agent {
  id: string;
  type: VehicleType;
  baseSpeed: number;
  edge: RoadEdge;
  /** Distance travelled along the edge in the current direction, metres. */
  dist: number;
  reversed: boolean;
  speed: number;
}

function weightedType(rand: () => number): (typeof VEHICLE_TYPES)[number] {
  const r = rand();
  let acc = 0;
  for (const t of VEHICLE_TYPES) {
    acc += t.weight;
    if (r <= acc) return t;
  }
  return VEHICLE_TYPES[0];
}

/** Vertex list of an edge in travel direction. */
function dirPath(edge: RoadEdge, reversed: boolean): LngLat[] {
  return reversed ? [...edge.path].reverse() : edge.path;
}

export function createMockProvider(seed = 42): TrafficDataProvider {
  const rand = mulberry32(seed);
  const snapshotListeners = new Set<(s: TrafficSnapshot) => void>();
  const statusListeners = new Set<(s: ProviderStatus) => void>();
  let timer: number | null = null;
  let startedAt = 0;
  let status: ProviderStatus = "offline";

  const agents: Agent[] = Array.from({ length: VEHICLE_COUNT }, (_, i) => {
    const t = weightedType(rand);
    const edge = pick(rand, roadEdges);
    return {
      id: `veh-${i.toString().padStart(3, "0")}`,
      type: t.type,
      baseSpeed: t.speed * (0.8 + rand() * 0.4),
      edge,
      dist: rand() * edge.lengthM,
      reversed: rand() < 0.5,
      speed: t.speed,
    };
  });

  // Two seeded incidents; a third candidate appears after 20 s to exercise the
  // "new anomaly" motion later. Coordinates snap to signal junctions.
  const incidentAnchors = signalJunctions.slice(0, 3);
  const incidents: Incident[] = [
    {
      id: "inc-001",
      type: "collision",
      severity: "high",
      latitude: incidentAnchors[0].lat,
      longitude: incidentAnchors[0].lng,
      confidence: 0.92,
      detectedAt: new Date().toISOString(),
      status: "confirmed",
      affectedIntersection: incidentAnchors[0].id,
    },
    {
      id: "inc-002",
      type: "breakdown",
      severity: "medium",
      latitude: incidentAnchors[1].lat,
      longitude: incidentAnchors[1].lng,
      confidence: 0.61,
      detectedAt: new Date().toISOString(),
      status: "candidate",
      affectedIntersection: incidentAnchors[1].id,
    },
  ];
  let thirdIncidentAdded = false;

  const engine = createDemoEngine();

  function signalPhase(index: number, elapsedS: number): SignalState {
    const offset = (index * 13) % SIGNAL_CYCLE_S;
    const p = (elapsedS + offset) % SIGNAL_CYCLE_S;
    if (p < GREEN_S) return "green";
    if (p < GREEN_S + YELLOW_S) return "yellow";
    return "red";
  }

  function nearestSignalState(
    lng: number,
    lat: number,
    elapsedS: number,
  ): { state: SignalState; distM: number } | null {
    let best: { state: SignalState; distM: number } | null = null;
    signalJunctions.forEach((j, i) => {
      const d = haversineMeters([lng, lat], [j.lng, j.lat]);
      if (!best || d < best.distM) {
        best = { state: signalPhase(i, elapsedS), distM: d };
      }
    });
    return best;
  }

  function step(elapsedS: number, advance = true) {
    const dt = advance ? TICK_MS / 1000 : 0;
    const perEdgeCount: Record<string, number> = {};

    for (const a of agents) {
      const path = dirPath(a.edge, a.reversed);
      const endPt = path[path.length - 1];

      // Ease off approaching a red/yellow light at the edge end.
      const distToEnd = a.edge.lengthM - a.dist;
      const sig = nearestSignalState(endPt[0], endPt[1], elapsedS);
      let target = a.baseSpeed * engine.speedFactor(a.edge.id);
      if (sig && sig.distM < 35 && distToEnd < 45 && sig.state !== "green") {
        target = 0.6;
      }
      a.speed += (target - a.speed) * 0.35;
      a.dist += a.speed * dt;

      if (a.dist >= a.edge.lengthM) {
        const overflow = a.dist - a.edge.lengthM;
        const links = edgeAdjacency.get(a.edge.id) ?? [];
        if (links.length) {
          const link = pick(rand, links);
          const nEdge = edgeById.get(link.edgeId);
          if (nEdge) {
            a.edge = nEdge;
            a.reversed = link.reversed;
            a.dist = Math.min(overflow, nEdge.lengthM);
          } else {
            a.edge = pick(rand, roadEdges);
            a.reversed = rand() < 0.5;
            a.dist = 0;
          }
        } else {
          a.edge = pick(rand, roadEdges);
          a.reversed = rand() < 0.5;
          a.dist = 0;
        }
      }
      perEdgeCount[a.edge.id] = (perEdgeCount[a.edge.id] ?? 0) + 1;
    }

    // ---- normalise to snapshot shapes -------------------------------------
    const now = new Date().toISOString();

    const vehicles: Vehicle[] = agents.map((a) => {
      // edge.cum is measured from edge.path[0]; when travelling reversed the
      // vehicle is `lengthM - dist` from that original start, heading flipped.
      const fromStart = a.reversed ? a.edge.lengthM - a.dist : a.dist;
      const p = pointAlongPath(a.edge.path, a.edge.cum, fromStart);
      return {
        id: a.id,
        type: a.type,
        latitude: p.lat,
        longitude: p.lng,
        speed: Math.max(0, a.speed) * 3.6,
        heading: a.reversed ? (p.headingDeg + 180) % 360 : p.headingDeg,
        lane: `${a.edge.id}#${a.reversed ? "r" : "f"}`,
        timestamp: now,
      };
    });

    const roadCongestion: Record<string, number> = {};
    for (const e of roadEdges) {
      const capacity = Math.max(
        1,
        (e.lengthM / SLOT_M) * Math.max(1, e.numLanes),
      );
      roadCongestion[e.id] = Math.max(engine.congestion(e.id), Math.min(1, (perEdgeCount[e.id] ?? 0) / capacity));
    }

    const intersections: Intersection[] = signalJunctions.map((j, i) => ({
      id: j.id,
      name: shortJunctionName(j.id),
      latitude: j.lat,
      longitude: j.lng,
      ...junctionVehicleStats([j.lng, j.lat], vehicles),
      signalState: signalPhase(i, elapsedS),
    }));

    if (!thirdIncidentAdded && elapsedS > 20) {
      const a = incidentAnchors[2] ?? incidentAnchors[0];
      incidents.push({
        id: "inc-003",
        type: "congestion",
        severity: "low",
        latitude: a.lat,
        longitude: a.lng,
        confidence: 0.48,
        detectedAt: new Date().toISOString(),
        status: "candidate",
        affectedIntersection: a.id,
      });
      thirdIncidentAdded = true;
    }

    const demo = engine.tick();

    const congestionAvg =
      Object.values(roadCongestion).reduce((s, v) => s + v, 0) /
      Math.max(1, Object.keys(roadCongestion).length);

    const snapshot: TrafficSnapshot = {
      timestamp: now,
      vehicles,
      intersections,
      incidents: incidents.map((i) => ({ ...i })),
      anomalies: demo.anomalies,
      emergencyRequests: demo.requests,
      roadCongestion,
      events: demo.events,
      summary: {
        operational: true,
        vehicleCount: vehicles.length,
        congestion: congestionAvg,
        signalsOnline: signalJunctions.length,
        signalsTotal: signalJunctions.length,
        lastUpdate: now,
      },
    };

    for (const l of snapshotListeners) l(snapshot);
  }

  function setStatus(next: ProviderStatus) {
    status = next;
    for (const l of statusListeners) l(next);
  }

  return {
    mode: "simulation",
    start() {
      if (timer !== null) return;
      setStatus("connecting");
      startedAt = Date.now();
      engine.start();
      engine.startDemoMission();
      setDemoCommandHandler((cmd) => {
        const result = engine.handle(cmd);
        // Answer straight away, as the live stream does, instead of on the next tick.
        step((Date.now() - startedAt) / 1000, false);
        return result;
      });
      window.setTimeout(() => setStatus("online"), 500);
      const loop = () => step((Date.now() - startedAt) / 1000);
      loop();
      timer = window.setInterval(loop, TICK_MS);
    },
    stop() {
      setDemoCommandHandler(null);
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
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
  };
}
