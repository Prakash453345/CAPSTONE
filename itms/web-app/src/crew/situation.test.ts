import { describe, expect, it } from "vitest";
import type { Anomaly, EmergencyRequest, GreenCorridorView, Intersection } from "@/types";
import type { RoutePlan } from "./plan";
import { alongFor, hasArrived, hazardsAhead, remainingSeconds, signalStatus, upcomingSignals } from "./situation";

// A straight 1 km route heading east, 0.001 degrees of longitude ~ 107 m at this latitude.
const LAT = 16.5;
const lng = (m: number) => 80.6 + m / 106_900;
const plan: RoutePlan = {
  edgeIds: ["e1", "e2", "e3"],
  coords: [[lng(0), LAT], [lng(1000), LAT]],
  cum: [0, 1000],
  totalM: 1000,
  maneuvers: [],
  spans: [
    { edgeId: "e1", startM: 0, endM: 300, name: "First Rd" },
    { edgeId: "e2", startM: 300, endM: 700, name: "Second Rd" },
    { edgeId: "e3", startM: 700, endM: 1000, name: "Third Rd" },
  ],
  signals: [
    { junctionId: "j1", name: "First at Second", atM: 300 },
    { junctionId: "j2", name: "Second at Third", atM: 700 },
    { junctionId: "j3", name: "Third at End", atM: 950 },
  ],
};

const junction = (id: string, over: Partial<Intersection> = {}): Intersection => ({
  id,
  name: id,
  latitude: LAT,
  longitude: 80.6,
  queueLength: 0,
  averageSpeed: 30,
  vehicleCount: 0,
  signalState: "red",
  ...over,
});

const corridor = (over: Partial<GreenCorridorView> = {}): GreenCorridorView => ({
  corridorId: "c1",
  status: "active",
  reservations: [
    { intersectionId: "j1", movements: [], openAtMs: 0, closeAtMs: 9000, order: 0 },
    { intersectionId: "j2", movements: [], openAtMs: 0, closeAtMs: 9000, order: 1 },
  ],
  passedIntersections: [],
  peakConcurrency: 1,
  ...over,
});

describe("signalStatus", () => {
  it("a fault outranks everything, even a held junction", () => {
    const fault = junction("j1", { preempted: true, signalState: "green", fault: { faultType: "comms_lost", detail: "", atMs: 0 } });
    expect(signalStatus(fault, corridor(), "j1")).toBe("fault");
  });

  it("a junction held for an emergency vehicle reads as held", () => {
    expect(signalStatus(junction("j1", { preempted: true }), corridor(), "j1")).toBe("held");
  });

  it("a junction the corridor has booked but not yet opened reads as arranged", () => {
    expect(signalStatus(junction("j2"), corridor(), "j2")).toBe("arranged");
  });

  it("without a corridor it falls back to the plain colour, red being the careful default", () => {
    expect(signalStatus(junction("j3", { signalState: "green" }), undefined, "j3")).toBe("green");
    expect(signalStatus(junction("j3", { signalState: "yellow" }), undefined, "j3")).toBe("amber");
    expect(signalStatus(junction("j3", { signalState: "red" }), undefined, "j3")).toBe("red");
    expect(signalStatus(undefined, undefined, "j3")).toBe("unknown");
  });
});

describe("upcomingSignals", () => {
  const all = [junction("j1", { preempted: true }), junction("j2"), junction("j3", { signalState: "green" })];

  it("lists signals ahead, nearest first, with distance and a plain-English line", () => {
    const list = upcomingSignals(plan, 100, { intersections: all, corridor: corridor() });
    expect(list.map((s) => s.junctionId)).toEqual(["j1", "j2", "j3"]);
    expect(list[0]).toMatchObject({ distM: 200, status: "held", tone: "ok" });
    expect(list[1]!.status).toBe("arranged");
    expect(list[2]!.status).toBe("green");
  });

  it("drops signals already passed, by position and by the corridor's own record", () => {
    expect(upcomingSignals(plan, 400, { intersections: all, corridor: corridor() }).map((s) => s.junctionId)).toEqual(["j2", "j3"]);
    const done = corridor({ passedIntersections: ["j2"] });
    expect(upcomingSignals(plan, 100, { intersections: all, corridor: done }).map((s) => s.junctionId)).toEqual(["j1", "j3"]);
  });

  it("honours the limit", () => {
    expect(upcomingSignals(plan, 0, { intersections: all, limit: 1 })).toHaveLength(1);
  });
});

describe("hazardsAhead", () => {
  const anomaly = (over: Partial<Anomaly>): Anomaly => ({
    id: "a1",
    source: "operator",
    kind: "accident",
    severity: "blocked",
    status: "active",
    edgeId: "e2",
    estimatedImpact: 1,
    startTime: "2026-10-17T00:00:00Z",
    ...over,
  });
  const base = { anomalies: [], congestion: {}, intersections: [], requests: [] };

  it("flags a blocked road ahead as critical, with how far away it is", () => {
    const [h] = hazardsAhead(plan, 100, { ...base, anomalies: [anomaly({})] });
    expect(h).toMatchObject({ kind: "closure", distM: 200, tone: "critical" });
    expect(h!.title).toContain("Accident");
  });

  it("calls a partial disruption a disruption, and ignores resolved or already-passed ones", () => {
    const partial = hazardsAhead(plan, 100, { ...base, anomalies: [anomaly({ severity: "medium", estimatedImpact: 0.4 })] });
    expect(partial[0]).toMatchObject({ kind: "disruption", tone: "warn" });
    expect(hazardsAhead(plan, 100, { ...base, anomalies: [anomaly({ status: "resolved" })] })).toEqual([]);
    expect(hazardsAhead(plan, 800, { ...base, anomalies: [anomaly({})] })).toEqual([]);
  });

  it("warns of heavy traffic ahead, not light", () => {
    expect(hazardsAhead(plan, 0, { ...base, congestion: { e3: 0.8 } })[0]).toMatchObject({ kind: "congestion", distM: 700 });
    expect(hazardsAhead(plan, 0, { ...base, congestion: { e3: 0.3 } })).toEqual([]);
  });

  it("only looks as far as the horizon", () => {
    expect(hazardsAhead(plan, 0, { ...base, congestion: { e3: 0.9 }, horizonM: 500 })).toEqual([]);
  });

  it("flags a faulted signal on the route", () => {
    const fault = junction("j2", { fault: { faultType: "power_restart", detail: "", atMs: 0 } });
    const [h] = hazardsAhead(plan, 0, { ...base, intersections: [fault] });
    expect(h).toMatchObject({ kind: "signal-fault", distM: 700, tone: "critical" });
  });

  it("notices another unit on the route but not your own, nor one far off it, nor a finished one", () => {
    const unit = (id: string, over: Partial<EmergencyRequest> = {}): EmergencyRequest => ({
      id,
      vehicleId: id,
      vehicleKind: "ambulance",
      state: "in_transit",
      sourceEdge: "e1",
      destinationEdge: "e3",
      alternatives: [],
      timeline: [],
      updatedAt: "",
      live: { lat: LAT, lon: lng(500), speedMps: 10, routeProgress: 0.5, status: "en_route" },
      ...over,
    });
    const requests = [
      unit("own"),
      unit("other"),
      unit("far", { live: { lat: LAT + 0.01, lon: lng(500), speedMps: 10, routeProgress: 0.5, status: "en_route" } }),
      unit("done", { state: "completed" }),
    ];
    const found = hazardsAhead(plan, 100, { ...base, requests, ownRequestId: "own", unitNames: (v) => `Unit ${v}` });
    expect(found.map((h) => h.id)).toEqual(["unit-other"]);
    expect(found[0]!.title).toBe("Unit other is on your route");
    expect(found[0]!.distM).toBeGreaterThan(350);
  });

  it("returns the nearest first", () => {
    const list = hazardsAhead(plan, 0, { ...base, anomalies: [anomaly({ edgeId: "e3" })], congestion: { e2: 0.9 } });
    expect(list.map((h) => h.kind)).toEqual(["congestion", "closure"]);
  });
});

describe("alongFor", () => {
  it("projects a reported position onto the route", () => {
    const hit = alongFor(plan, { lat: LAT, lon: lng(400), speedMps: 8, routeProgress: 0, status: "en_route" });
    expect(hit.alongM).toBeGreaterThan(395);
    expect(hit.alongM).toBeLessThan(405);
    expect(hit.offRouteM).toBeLessThan(1);
  });

  it("falls back to the reported progress when there is no position", () => {
    expect(alongFor(plan, { speedMps: 0, routeProgress: 0.25, status: "assigned" }).alongM).toBe(250);
    expect(alongFor(plan, undefined).alongM).toBe(0);
    expect(alongFor(plan, { speedMps: 0, routeProgress: 7, status: "assigned" }).alongM).toBe(1000);
  });

  it("reports when the vehicle has left the route", () => {
    expect(alongFor(plan, { lat: LAT + 0.01, lon: lng(400), speedMps: 8, routeProgress: 0, status: "en_route" }).offRouteM).toBeGreaterThan(500);
  });
});

describe("remainingSeconds and hasArrived", () => {
  const req = (over: Partial<EmergencyRequest> = {}): EmergencyRequest => ({
    id: "r",
    vehicleId: "v",
    vehicleKind: "ambulance",
    state: "in_transit",
    sourceEdge: "a",
    destinationEdge: "b",
    alternatives: [],
    timeline: [],
    updatedAt: "",
    ...over,
  });

  it("prefers the unit's own ETA, then its speed, then the plan's pace", () => {
    expect(remainingSeconds(req({ live: { speedMps: 10, etaS: 42, routeProgress: 0, status: "en_route" } }), 500)).toBe(42);
    expect(remainingSeconds(req({ etaS: 90 }), 500)).toBe(90);
    expect(remainingSeconds(req({ live: { speedMps: 10, routeProgress: 0, status: "en_route" } }), 500)).toBe(50);
    expect(remainingSeconds(req(), 500)).toBeNull();
  });

  it("knows it has arrived however that is reported", () => {
    expect(hasArrived(req({ state: "completed" }), 900)).toBe(true);
    expect(hasArrived(req({ live: { speedMps: 0, routeProgress: 1, status: "arrived" } }), 900)).toBe(true);
    expect(hasArrived(req(), 10)).toBe(true);
    expect(hasArrived(req(), 300)).toBe(false);
  });
});
