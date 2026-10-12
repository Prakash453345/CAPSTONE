import { describe, expect, it } from "vitest";
import {
  buildCorridorFeatures,
  buildPointFeatures,
  buildRouteFeatures,
  buildSegmentFeatures,
  buildVehicleFrames,
  edgeMidpoint,
  edgesToCoords,
  trimRoute,
} from "@/components/map/emergencyGeo";
import { edgeById } from "@/data/network";
import { colorForRequest } from "@/components/map/emergencyColors";
import { CORRIDOR_ACCENT_COLOR, EV_ROUTE_COLOR } from "@/components/map/mapColors";
import type {
  EmergencyRequest,
  EmergencyRequestState,
  EmergencyRouteView,
  GreenCorridorView,
} from "@/types";

// Real ids from the bundled Vijayawada corridor network, so edgeById /
// junctionById lookups inside emergencyGeo.ts actually resolve.
const EDGE_A = "-177626285";
const EDGE_B = "-343269496";
const EDGE_C = "-679017002";
const SIGNAL_JUNCTION = "1880441505";

function route(edges: string[], rank = 0, over: Partial<EmergencyRouteView> = {}): EmergencyRouteView {
  return {
    edges,
    rank,
    totalDistanceM: 1000,
    totalTravelTimeS: 90,
    etaS: 100,
    nIntersections: edges.length - 1,
    signalisedIntersections: [],
    congestedSegments: [],
    anomalousSegmentsAvoided: [],
    forcedThrough: [],
    reliable: true,
    cost: {
      travelTimeS: 90, congestion: 1, anomaly: 0, signalDelayS: 6,
      disruption: 0.4, reliability: 0.1, score: 12,
    },
    weightsUsed: {},
    ...over,
  };
}

function corridor(over: Partial<GreenCorridorView> = {}): GreenCorridorView {
  return {
    corridorId: "gc-1",
    status: "active",
    reservations: [{ intersectionId: SIGNAL_JUNCTION, movements: ["L0"], openAtMs: 0, closeAtMs: 1000, order: 0 }],
    passedIntersections: [],
    peakConcurrency: 1,
    ...over,
  };
}

function req(id: string, over: Partial<EmergencyRequest> = {}): EmergencyRequest {
  return {
    id,
    vehicleId: `v-${id}`,
    vehicleKind: "ambulance",
    state: "in_transit",
    sourceEdge: EDGE_A,
    destinationEdge: EDGE_C,
    alternatives: [],
    timeline: [],
    updatedAt: new Date().toISOString(),
    ...over,
  };
}

const terminalStates: EmergencyRequestState[] = ["completed", "cancelled"];

describe("edgesToCoords / edgeMidpoint", () => {
  it("concatenates real edges' paths and skips unknown ones", () => {
    const coords = edgesToCoords([EDGE_A, "not-a-real-edge", EDGE_B]);
    expect(coords.length).toBeGreaterThan(0);
  });

  it("returns null for an unknown or missing edge", () => {
    expect(edgeMidpoint(undefined)).toBeNull();
    expect(edgeMidpoint("not-a-real-edge")).toBeNull();
    expect(edgeMidpoint(EDGE_A)).not.toBeNull();
  });
});

describe("buildRouteFeatures — multiple active requests", () => {
  it("draws every driving vehicle's route, not just the selected one", () => {
    const r1 = req("er-1", { route: route([EDGE_A, EDGE_B]) });
    const r2 = req("er-2", { route: route([EDGE_B, EDGE_C]) });
    const features = buildRouteFeatures([r1, r2], "er-1", 0);
    const mains = features.filter((f) => f.properties.kind === "main");
    expect(mains.map((f) => f.properties.requestId).sort()).toEqual(["er-1", "er-2"]);
  });

  it("gives every mission's route the same constant colour, but its own geometry", () => {
    // Every route reads as "the optimal route" at a glance regardless of
    // which mission it belongs to -- unlike the vehicle marker, it is
    // deliberately NOT hashed per request (see EV_ROUTE_COLOR's doc comment).
    const r1 = req("er-1", { route: route([EDGE_A]) });
    const r2 = req("er-2", { route: route([EDGE_C]) });
    const [f1, f2] = buildRouteFeatures([r1, r2], null, 0);
    expect(f1.properties.color).toBe(EV_ROUTE_COLOR);
    expect(f2.properties.color).toBe(EV_ROUTE_COLOR);
    expect(f1.geometry.coordinates).not.toEqual(f2.geometry.coordinates);
  });

  it("draws the selected plan with its alternatives, and nothing for an unselected plan", () => {
    const r1 = req("er-1", {
      state: "route_ready",
      route: route([EDGE_A], 0),
      alternatives: [route([EDGE_B], 1), route([EDGE_C], 2)],
    });
    const r2 = req("er-2", {
      state: "route_ready",
      route: route([EDGE_B], 0),
      alternatives: [route([EDGE_C], 1)],
    });
    const features = buildRouteFeatures([r1, r2], "er-1", 0);
    expect(features.every((f) => f.properties.requestId === "er-1")).toBe(true);
    expect(features.filter((f) => f.properties.kind === "alt")).toHaveLength(2);
    expect(features.filter((f) => f.properties.kind === "main")).toHaveLength(1);
  });

  it("drops a planned route from the map once it is deselected", () => {
    const planned = req("er-1", { state: "route_ready", route: route([EDGE_A]) });
    expect(buildRouteFeatures([planned], "er-1", 0)).toHaveLength(1);
    expect(buildRouteFeatures([planned], null, 0)).toEqual([]);
  });

  it("shows no alternatives once the vehicle is driving", () => {
    const driving = req("er-1", {
      route: route([EDGE_A], 0),
      alternatives: [route([EDGE_B], 1)],
    });
    const features = buildRouteFeatures([driving], "er-1", 1);
    expect(features).toHaveLength(1);
    expect(features[0].properties.kind).toBe("main");
    expect(features[0].geometry.coordinates).toEqual(edgesToCoords([EDGE_A]));
  });

  it("draws a driving route only from the vehicle onward", () => {
    const path = edgeById.get(EDGE_A)!.path;
    const i = Math.floor(path.length / 2);
    const cut = { lng: path[i][0], lat: path[i][1], edgeId: EDGE_A };
    const driving = req("er-1", { route: route([EDGE_A, EDGE_B]) });
    const [f] = buildRouteFeatures([driving], null, 0, new Map([["er-1", cut]]));
    const coords = f.geometry.coordinates;
    expect(coords[0][0]).toBeCloseTo(cut.lng, 9);
    expect(coords[0][1]).toBeCloseTo(cut.lat, 9);
    expect(coords[coords.length - 1]).toEqual(edgesToCoords([EDGE_B]).at(-1));
    expect(coords.length).toBeLessThan(edgesToCoords([EDGE_A, EDGE_B]).length);
  });
});

describe("buildRouteFeatures — selected-request emphasis & switching", () => {
  const r1 = req("er-1", { route: route([EDGE_A]) });
  const r2 = req("er-2", { route: route([EDGE_B]) });

  it("marks only the selected request's main route as selected", () => {
    const features = buildRouteFeatures([r1, r2], "er-1", 0);
    const byId = Object.fromEntries(features.map((f) => [f.properties.requestId, f.properties.selected]));
    expect(byId["er-1"]).toBe(true);
    expect(byId["er-2"]).toBe(false);
  });

  it("switching the selected id flips emphasis without dropping any request", () => {
    const before = buildRouteFeatures([r1, r2], "er-1", 0);
    const after = buildRouteFeatures([r1, r2], "er-2", 0);
    expect(before.map((f) => f.properties.requestId).sort()).toEqual(
      after.map((f) => f.properties.requestId).sort(),
    );
    expect(before.find((f) => f.properties.requestId === "er-1")?.properties.selected).toBe(true);
    expect(after.find((f) => f.properties.requestId === "er-1")?.properties.selected).toBe(false);
    expect(after.find((f) => f.properties.requestId === "er-2")?.properties.selected).toBe(true);
  });

  it("selecting nothing (null) leaves every request de-emphasised but present", () => {
    const features = buildRouteFeatures([r1, r2], null, 0);
    expect(features).toHaveLength(2);
    expect(features.every((f) => f.properties.selected === false)).toBe(true);
  });

  it("previewing an alternative promotes it to the selected request's main line", () => {
    const withAlt = req("er-1", {
      state: "route_ready",
      route: route([EDGE_A], 0),
      alternatives: [route([EDGE_B], 1)],
    });
    const previewingAlt = buildRouteFeatures([withAlt], "er-1", 1);
    const main = previewingAlt.find((f) => f.properties.kind === "main");
    const alt = previewingAlt.find((f) => f.properties.kind === "alt");
    expect(main?.geometry.coordinates).toEqual(edgesToCoords([EDGE_B]));
    expect(alt?.geometry.coordinates).toEqual(edgesToCoords([EDGE_A]));
  });
});

describe("buildSegmentFeatures", () => {
  it("only surfaces congested/avoided segments for the selected request", () => {
    const r1 = req("er-1", {
      route: route([EDGE_A], 0, { congestedSegments: [EDGE_A], anomalousSegmentsAvoided: [EDGE_B] }),
    });
    const r2 = req("er-2", {
      route: route([EDGE_C], 0, { congestedSegments: [EDGE_C] }),
    });
    const features = buildSegmentFeatures([r1, r2], "er-1", 0);
    expect(features.every((f) => f.properties.requestId === "er-1")).toBe(true);
    expect(features.some((f) => f.properties.kind === "congest")).toBe(true);
    expect(features.some((f) => f.properties.kind === "avoid")).toBe(true);
  });

  it("is empty when nothing is selected", () => {
    const r1 = req("er-1", { route: route([EDGE_A], 0, { congestedSegments: [EDGE_A] }) });
    expect(buildSegmentFeatures([r1], null, 0)).toEqual([]);
  });
});

describe("buildPointFeatures", () => {
  it("draws start and destination for the selected plan, nothing for other plans", () => {
    const r1 = req("er-1", { state: "route_ready", sourceEdge: EDGE_A, destinationEdge: EDGE_B });
    const r2 = req("er-2", { state: "route_ready", sourceEdge: EDGE_B, destinationEdge: EDGE_C });
    const features = buildPointFeatures([r1, r2], "er-1", null);
    expect(features).toHaveLength(2);
    expect(features.every((f) => f.properties.requestId === "er-1")).toBe(true);
  });

  it("draws only the destination for a driving vehicle (its start is behind it)", () => {
    const r1 = req("er-1", { sourceEdge: EDGE_A, destinationEdge: EDGE_B });
    const r2 = req("er-2", { sourceEdge: EDGE_B, destinationEdge: EDGE_C });
    const features = buildPointFeatures([r1, r2], "er-1", null);
    expect(features).toHaveLength(2);
    expect(features.map((f) => f.geometry.coordinates)).toEqual([
      edgeMidpoint(EDGE_B),
      edgeMidpoint(EDGE_C),
    ]);
  });

  it("includes the operator's in-progress draft, always at full prominence", () => {
    const draft = {
      unit: { id: "EV-001", callSign: "Ambulance 12", kind: "ambulance" as const },
      source: { edgeId: EDGE_A, edgeName: null, at: [80.6, 16.5] as [number, number] },
      destination: null,
    };
    const features = buildPointFeatures([], null, draft);
    expect(features).toHaveLength(1);
    expect(features[0].properties.requestId).toBeNull();
    expect(features[0].properties.selected).toBe(true);
  });
});

describe("buildCorridorFeatures", () => {
  it("renders a corridor for every active request that has one, not just the selected one", () => {
    const r1 = req("er-1", { corridor: corridor() });
    const r2 = req("er-2", { corridor: corridor({ corridorId: "gc-2" }) });
    const features = buildCorridorFeatures([r1, r2], "er-1");
    expect(features.map((f) => f.properties.requestId).sort()).toEqual(["er-1", "er-2"]);
    const byId = Object.fromEntries(features.map((f) => [f.properties.requestId, f.properties]));
    expect(byId["er-1"].selected).toBe(true);
    expect(byId["er-2"].selected).toBe(false);
    // Same constant accent for every mission's corridor -- see
    // CORRIDOR_ACCENT_COLOR's doc comment (one consistent "held for an EV"
    // colour, shared with SignalLayer's preemption ring).
    expect(byId["er-1"].color).toBe(CORRIDOR_ACCENT_COLOR);
    expect(byId["er-2"].color).toBe(CORRIDOR_ACCENT_COLOR);
  });

  it("marks a passed junction as not held", () => {
    const r1 = req("er-1", {
      corridor: corridor({ passedIntersections: [SIGNAL_JUNCTION] }),
    });
    const [f] = buildCorridorFeatures([r1], "er-1");
    expect(f.properties.held).toBe(false);
  });

  it("skips a request with no corridor", () => {
    const r1 = req("er-1");
    expect(buildCorridorFeatures([r1], "er-1")).toEqual([]);
  });
});

describe("buildVehicleFrames — multiple emergency vehicles", () => {
  it("returns one frame per active request with a live position", () => {
    const r1 = req("er-1", { live: { lat: 16.5, lon: 80.6, speedMps: 8, routeProgress: 0.3, status: "en_route" } });
    const r2 = req("er-2", { live: { lat: 16.51, lon: 80.61, speedMps: 6, routeProgress: 0.6, status: "en_route" } });
    const frames = buildVehicleFrames([r1, r2], "er-2");
    expect(frames.size).toBe(2);
    expect(frames.get("er-1")?.selected).toBe(false);
    expect(frames.get("er-2")?.selected).toBe(true);
    expect(frames.get("er-1")?.color).toBe(colorForRequest("er-1"));
    expect(frames.get("er-2")?.color).toBe(colorForRequest("er-2"));
  });

  it("associates each frame with the correct vehicle kind", () => {
    const ambulance = req("er-1", {
      vehicleKind: "ambulance",
      live: { lat: 16.5, lon: 80.6, speedMps: 8, routeProgress: 0.1, status: "en_route" },
    });
    const police = req("er-2", {
      vehicleKind: "police",
      live: { lat: 16.5, lon: 80.6, speedMps: 8, routeProgress: 0.1, status: "en_route" },
    });
    const frames = buildVehicleFrames([ambulance, police], null);
    expect(frames.get("er-1")?.kind).toBe("ambulance");
    expect(frames.get("er-2")?.kind).toBe("police");
  });

  it("skips a request with no live position yet", () => {
    const r1 = req("er-1"); // no `live`
    expect(buildVehicleFrames([r1], null).size).toBe(0);
  });
});

describe("completed / cancelled request handling", () => {
  it.each(terminalStates)("excludes a %s request's route from the map", (state) => {
    const r = req("er-1", { state, route: route([EDGE_A]) });
    expect(buildRouteFeatures([r], "er-1", 0)).toEqual([]);
  });

  it.each(terminalStates)("excludes a %s request's points from the map", (state) => {
    const r = req("er-1", { state });
    expect(buildPointFeatures([r], "er-1", null)).toEqual([]);
  });

  it.each(terminalStates)("excludes a %s request's corridor from the map", (state) => {
    const r = req("er-1", { state, corridor: corridor() });
    expect(buildCorridorFeatures([r], "er-1")).toEqual([]);
  });

  it.each(terminalStates)("excludes a %s request's vehicle from the map", (state) => {
    const r = req("er-1", {
      state,
      live: { lat: 16.5, lon: 80.6, speedMps: 0, routeProgress: 1, status: "arrived" },
    });
    expect(buildVehicleFrames([r], "er-1").size).toBe(0);
  });

  it("a terminal request never displaces an active sibling's rendering", () => {
    const done = req("er-1", { state: "completed", route: route([EDGE_A]) });
    const active = req("er-2", { route: route([EDGE_B]) });
    const features = buildRouteFeatures([done, active], "er-2", 0);
    expect(features.map((f) => f.properties.requestId)).toEqual(["er-2"]);
  });
});

describe("trimRoute", () => {
  const path = (id: string) => edgeById.get(id)!.path;

  it("starts at the vehicle projected onto the route and keeps the rest", () => {
    const a = path(EDGE_A);
    const mid = [(a[0][0] + a[1][0]) / 2, (a[0][1] + a[1][1]) / 2];
    // a little off the line: the start is its projection, not the raw point
    const off = { lng: mid[0] + 0.00001, lat: mid[1] - 0.00001, edgeId: EDGE_A };
    const out = trimRoute([EDGE_A, EDGE_B], off);
    expect(out.slice(1)).toEqual(edgesToCoords([EDGE_A, EDGE_B]).slice(1));
    const [sx, sy] = out[0];
    const cross = (a[1][0] - a[0][0]) * (sy - a[0][1]) - (a[1][1] - a[0][1]) * (sx - a[0][0]);
    expect(Math.abs(cross)).toBeLessThan(1e-12); // on segment 0
  });

  it("uses the vehicle's road to choose between two stretches that run close together", () => {
    // the same road both ways: the reverse carriageway is metres away
    const fwd = "177626285";
    const rev = "-177626285";
    if (!edgeById.has(fwd) || !edgeById.has(rev)) return;
    const p = path(rev);
    const at = p[Math.floor(p.length / 2)];
    const out = trimRoute([fwd, rev], { lng: at[0], lat: at[1], edgeId: rev });
    // what is left is part of the reverse carriageway only
    const tail = out.slice(1);
    expect(tail.length).toBeGreaterThan(0);
    for (const c of tail) expect(p).toContainEqual(c);
  });

  it("falls back to progress along the route when the vehicle is inside a junction", () => {
    const coords = edgesToCoords([EDGE_A, EDGE_B]);
    const end = coords.at(-1)!;
    const out = trimRoute([EDGE_A, EDGE_B], { lng: end[0], lat: end[1], edgeId: ":j_0_0", progress: 1 });
    expect(out).toHaveLength(2);
    expect(out.at(-1)).toEqual(end);
  });
});
