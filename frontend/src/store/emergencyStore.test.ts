import { beforeEach, describe, expect, it } from "vitest";
import {
  CREW_TYPES,
  corridorHoldSeconds,
  draftLatLng,
  isTerminalRequest,
  nextCorridorReservation,
  orderedReservations,
  requestRoutes,
  rerouteCount,
  selectActiveRequests,
  selectPreviewedRoute,
  selectSelectedRequest,
  selectVisibleRequests,
  useEmergencyStore,
} from "@/store/emergencyStore";
import type {
  EmergencyRequest,
  EmergencyRouteView,
  GreenCorridorView,
  RequestTimelineEntry,
} from "@/types";

function reset() {
  useEmergencyStore.setState({
    requests: [],
    selectedRequestId: null,
    draft: null,
    previewRank: 0,
    archivedRequestIds: new Set(),
  });
}

function route(rank: number, edges: string[], score: number): EmergencyRouteView {
  return {
    edges,
    rank,
    totalDistanceM: 1000 + rank * 200,
    totalTravelTimeS: 90 + rank * 10,
    etaS: 100 + rank * 12,
    nIntersections: edges.length - 1,
    signalisedIntersections: [],
    congestedSegments: [],
    anomalousSegmentsAvoided: [],
    forcedThrough: [],
    reliable: true,
    cost: {
      travelTimeS: 90,
      congestion: 1,
      anomaly: 0,
      signalDelayS: 6,
      disruption: 0.4,
      reliability: 0.1,
      score,
    },
    weightsUsed: { travel_time_weight: 1, anomaly_weight: 1 },
  };
}

const req = (id: string, over: Partial<EmergencyRequest> = {}): EmergencyRequest => ({
  id,
  vehicleId: `v-${id}`,
  vehicleKind: "ambulance",
  state: "route_ready",
  sourceEdge: "S",
  destinationEdge: "T",
  alternatives: [],
  timeline: [],
  updatedAt: new Date().toISOString(),
  ...over,
});

function corridor(over: Partial<GreenCorridorView> = {}): GreenCorridorView {
  return {
    corridorId: "gc-1",
    status: "active",
    reservations: [
      { intersectionId: "J1", movements: ["L0"], openAtMs: 15_000, closeAtMs: 34_000, order: 0 },
      { intersectionId: "J2", movements: ["L1"], openAtMs: 40_000, closeAtMs: 55_000, order: 1 },
    ],
    passedIntersections: [],
    peakConcurrency: 1,
    ...over,
  };
}

describe("emergencyStore", () => {
  beforeEach(reset);

  it("startDraft seeds a draft with the chosen unit and no points", () => {
    useEmergencyStore.getState().startDraft(CREW_TYPES[2]!);
    const d = useEmergencyStore.getState().draft;
    expect(d?.unit.kind).toBe("fire_truck");
    expect(d?.source).toBeNull();
    expect(d?.destination).toBeNull();
  });

  it("setDraftPoint fills one end and is a no-op without a draft", () => {
    useEmergencyStore.getState().setDraftPoint("source", { edgeId: "A", edgeName: "A", at: [1, 2] });
    expect(useEmergencyStore.getState().draft).toBeNull();

    useEmergencyStore.getState().startDraft(CREW_TYPES[0]!);
    useEmergencyStore
      .getState()
      .setDraftPoint("destination", { edgeId: "B", edgeName: null, at: [3, 4] });
    expect(useEmergencyStore.getState().draft?.destination?.edgeId).toBe("B");
    expect(useEmergencyStore.getState().draft?.source).toBeNull();
  });

  it("clearDraft removes the draft", () => {
    useEmergencyStore.getState().startDraft(CREW_TYPES[0]!);
    useEmergencyStore.getState().clearDraft();
    expect(useEmergencyStore.getState().draft).toBeNull();
  });

  it("selectSelectedRequest resolves the id to a request", () => {
    useEmergencyStore.setState({ requests: [req("er-1"), req("er-2")], selectedRequestId: "er-2" });
    expect(selectSelectedRequest(useEmergencyStore.getState())?.id).toBe("er-2");
    useEmergencyStore.setState({ selectedRequestId: "ghost" });
    expect(selectSelectedRequest(useEmergencyStore.getState())).toBeNull();
  });

  it("draftLatLng converts a [lng,lat] point or passes null through", () => {
    expect(draftLatLng({ edgeId: "A", edgeName: null, at: [80.6, 16.5] })).toEqual({
      longitude: 80.6,
      latitude: 16.5,
    });
    expect(draftLatLng(null)).toBeNull();
  });

  // ---- route preview (Phase 2) ----------------------------------------

  it("requestRoutes returns recommended first, then alternatives", () => {
    const r = req("er-1", {
      route: route(0, ["S", "A", "T"], 10),
      alternatives: [route(1, ["S", "B", "T"], 14), route(2, ["S", "C", "T"], 18)],
    });
    const rs = requestRoutes(r);
    expect(rs.map((x) => x.rank)).toEqual([0, 1, 2]);
    expect(requestRoutes(null)).toEqual([]);
    expect(requestRoutes(req("er-2"))).toEqual([]); // no route yet
  });

  it("selectPreviewedRoute follows previewRank and falls back to recommended", () => {
    useEmergencyStore.setState({
      requests: [
        req("er-1", {
          route: route(0, ["S", "A", "T"], 10),
          alternatives: [route(1, ["S", "B", "T"], 14)],
        }),
      ],
      selectedRequestId: "er-1",
      previewRank: 0,
    });
    expect(selectPreviewedRoute(useEmergencyStore.getState())?.rank).toBe(0);

    useEmergencyStore.getState().setPreviewRank(1);
    expect(selectPreviewedRoute(useEmergencyStore.getState())?.rank).toBe(1);

    useEmergencyStore.getState().setPreviewRank(9); // out of range -> recommended
    expect(selectPreviewedRoute(useEmergencyStore.getState())?.rank).toBe(0);
  });

  it("selectRequest resets previewRank to 0", () => {
    useEmergencyStore.setState({
      requests: [req("er-1", { route: route(0, ["S", "T"], 5) })],
      previewRank: 2,
    });
    useEmergencyStore.getState().selectRequest("er-1");
    expect(useEmergencyStore.getState().previewRank).toBe(0);
  });

  // ---- active-request set (Phase 3) ------------------------------------

  it("isTerminalRequest is true only for completed/cancelled", () => {
    expect(isTerminalRequest(req("er-1", { state: "completed" }))).toBe(true);
    expect(isTerminalRequest(req("er-1", { state: "cancelled" }))).toBe(true);
    expect(isTerminalRequest(req("er-1", { state: "in_transit" }))).toBe(false);
    expect(isTerminalRequest(req("er-1", { state: "route_ready" }))).toBe(false);
  });

  it("selectActiveRequests excludes terminal requests", () => {
    useEmergencyStore.setState({
      requests: [
        req("er-1", { state: "in_transit" }),
        req("er-2", { state: "completed" }),
        req("er-3", { state: "cancelled" }),
        req("er-4", { state: "route_ready" }),
      ],
    });
    expect(selectActiveRequests(useEmergencyStore.getState()).map((r) => r.id)).toEqual([
      "er-1", "er-4",
    ]);
  });

  // ---- green corridor (Phase 4) ----------------------------------------

  it("orderedReservations sorts by route order regardless of wire order", () => {
    const c = corridor({
      reservations: [
        { intersectionId: "J2", movements: [], openAtMs: 0, closeAtMs: 0, order: 1 },
        { intersectionId: "J1", movements: [], openAtMs: 0, closeAtMs: 0, order: 0 },
      ],
    });
    expect(orderedReservations(c).map((r) => r.intersectionId)).toEqual(["J1", "J2"]);
  });

  it("nextCorridorReservation is the first not-yet-passed junction in route order", () => {
    const c = corridor();
    expect(nextCorridorReservation(c)?.intersectionId).toBe("J1");
    expect(nextCorridorReservation(corridor({ passedIntersections: ["J1"] }))?.intersectionId).toBe(
      "J2",
    );
  });

  it("nextCorridorReservation is null once every junction is cleared", () => {
    const c = corridor({ passedIntersections: ["J1", "J2"] });
    expect(nextCorridorReservation(c)).toBeNull();
  });

  it("corridorHoldSeconds is a duration, not a countdown to a wall-clock time", () => {
    // openAtMs/closeAtMs are sim-clock, not the browser's -- only the
    // difference between them is meaningful client-side.
    expect(corridorHoldSeconds({ openAtMs: 15_000, closeAtMs: 34_000 })).toBe(19);
    expect(corridorHoldSeconds({ openAtMs: 1_700_000_000_000, closeAtMs: 1_700_000_019_000 })).toBe(
      19,
    );
  });

  it("corridorHoldSeconds never goes negative", () => {
    expect(corridorHoldSeconds({ openAtMs: 1000, closeAtMs: 500 })).toBe(0);
  });

  // ---- mission archive + summary (Phase 6) ------------------------------

  it("archiveRequest hides a request from selectVisibleRequests but not from requests", () => {
    useEmergencyStore.setState({
      requests: [req("er-1", { state: "completed" }), req("er-2", { state: "in_transit" })],
    });
    useEmergencyStore.getState().archiveRequest("er-1");
    expect(useEmergencyStore.getState().requests.map((r) => r.id)).toEqual(["er-1", "er-2"]);
    expect(selectVisibleRequests(useEmergencyStore.getState()).map((r) => r.id)).toEqual(["er-2"]);
  });

  it("archiveRequest is idempotent and only affects the given id", () => {
    useEmergencyStore.setState({ requests: [req("er-1", { state: "completed" })] });
    useEmergencyStore.getState().archiveRequest("er-1");
    useEmergencyStore.getState().archiveRequest("er-1");
    expect(useEmergencyStore.getState().archivedRequestIds.size).toBe(1);
  });

  function entry(state: EmergencyRequest["state"], atMs = 0): RequestTimelineEntry {
    return { state, detail: "", actor: "system:router", atMs };
  }

  it("rerouteCount counts same-state-as-previous timeline entries", () => {
    expect(
      rerouteCount({
        timeline: [
          entry("routing"),
          entry("route_ready"), // initial plan -- not a reroute
          entry("route_ready"), // operator RECALCULATE -- a reroute
          entry("green_corridor_active"), // real transition -- not a reroute
          entry("in_transit"),
          entry("in_transit"), // auto-reroute in flight -- a reroute
          entry("completed"),
        ],
      }),
    ).toBe(2);
  });

  it("rerouteCount is 0 for an empty or single-entry timeline", () => {
    expect(rerouteCount({ timeline: [] })).toBe(0);
    expect(rerouteCount({ timeline: [entry("route_ready")] })).toBe(0);
  });
});
