import { describe, expect, it } from "vitest";
import {
  mapCorridor,
  mapRoute,
  mapVehicleLive,
  mergePassed,
  msToIso,
  pushTimelineEntry,
  toMs,
} from "@/services/traffic/wsMappers";
import type { RequestTimelineEntry } from "@/types";

describe("msToIso / toMs", () => {
  it("passes ISO strings through and converts epoch-ms numbers", () => {
    expect(msToIso("2026-09-10T12:00:00.000Z")).toBe("2026-09-10T12:00:00.000Z");
    expect(msToIso(0)).toBe("1970-01-01T00:00:00.000Z");
  });

  it("toMs parses both shapes and falls back on garbage", () => {
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(toMs("2026-09-10T12:00:00.000Z")).toBe(Date.parse("2026-09-10T12:00:00.000Z"));
    const before = Date.now();
    expect(toMs(undefined)).toBeGreaterThanOrEqual(before);
  });
});

describe("mapRoute", () => {
  it("returns undefined for a missing route", () => {
    expect(mapRoute(null)).toBeUndefined();
    expect(mapRoute(undefined)).toBeUndefined();
  });

  it("maps snake_case RouteSummary to camelCase with numeric coercion", () => {
    const r = mapRoute({
      edges: ["A", "B", "T"],
      rank: 1,
      total_distance_m: 1234.5,
      total_travel_time_s: 90,
      eta_s: 110,
      n_intersections: 2,
      signalised_intersections: ["J1"],
      congested_segments: ["B"],
      anomalous_segments_avoided: ["X"],
      reliable: true,
      cost_travel_time_s: 90,
      cost_congestion: 1.2,
      cost_anomaly: 0,
      cost_signal_delay_s: 6,
      cost_disruption: 0.4,
      cost_reliability: 0.1,
      route_score: 12.3,
      weights_used: { anomaly_weight: 1, travel_time_weight: 1 },
    });
    expect(r).toMatchObject({
      edges: ["A", "B", "T"],
      rank: 1,
      totalDistanceM: 1234.5,
      etaS: 110,
      signalisedIntersections: ["J1"],
      congestedSegments: ["B"],
      anomalousSegmentsAvoided: ["X"],
      reliable: true,
    });
    expect(r?.cost.score).toBe(12.3);
    expect(r?.cost.signalDelayS).toBe(6);
    expect(r?.weightsUsed).toEqual({ anomaly_weight: 1, travel_time_weight: 1 });
  });

  it("tolerates a sparse payload with sensible defaults", () => {
    const r = mapRoute({ edges: ["A"] });
    expect(r?.edges).toEqual(["A"]);
    expect(r?.totalDistanceM).toBe(0);
    expect(r?.reliable).toBe(false);
    expect(r?.weightsUsed).toEqual({});
  });
});

describe("mapCorridor", () => {
  it("maps reservations and reads status lowercased", () => {
    const c = mapCorridor({
      corridor_id: "gc-0001",
      status: "ACTIVE",
      peak_concurrency: 2,
      reservations: [
        { intersection_id: "J1", movements: ["L0"], open_at_ms: 10, close_at_ms: 40, order: 0 },
        { intersection_id: "J2", movements: ["L1"], open_at_ms: 30, close_at_ms: 60, order: 1 },
      ],
    });
    expect(c.corridorId).toBe("gc-0001");
    expect(c.status).toBe("active");
    expect(c.peakConcurrency).toBe(2);
    expect(c.reservations.map((r) => r.intersectionId)).toEqual(["J1", "J2"]);
    expect(c.passedIntersections).toEqual([]);
  });

  it("extracts the cleared junction from a junction_passed event", () => {
    const c = mapCorridor({
      corridor_id: "gc-1",
      status: "active",
      event: "junction_passed",
      detail: "J1",
      reservations: [],
    });
    expect(c.passedIntersections).toEqual(["J1"]);
  });
});

describe("mergePassed", () => {
  it("unions prior and new sets without duplicates", () => {
    expect(mergePassed(["J1"], ["J1", "J2"])).toEqual(["J1", "J2"]);
    expect(mergePassed(undefined, ["J3"])).toEqual(["J3"]);
    expect(mergePassed(["J1", "J2"], [])).toEqual(["J1", "J2"]);
  });
});

describe("mapVehicleLive", () => {
  it("coerces numbers and lowercases status", () => {
    const v = mapVehicleLive({
      lat: 16.5,
      lon: 80.6,
      edge_id: "A",
      speed_mps: 8.2,
      eta_s: 42,
      route_progress: 0.37,
      status: "EN_ROUTE",
    });
    expect(v).toEqual({
      lat: 16.5,
      lon: 80.6,
      edgeId: "A",
      speedMps: 8.2,
      etaS: 42,
      routeProgress: 0.37,
      status: "en_route",
    });
  });

  it("keeps missing lat/lon/eta undefined", () => {
    const v = mapVehicleLive({ speed_mps: 0, route_progress: 0 });
    expect(v.lat).toBeUndefined();
    expect(v.lon).toBeUndefined();
    expect(v.etaS).toBeUndefined();
    expect(v.status).toBe("en_route");
  });
});

describe("pushTimelineEntry", () => {
  const entry = (state: string, detail = "", atMs = 0): RequestTimelineEntry => ({
    state: state as RequestTimelineEntry["state"],
    detail,
    actor: "system",
    atMs,
  });

  it("appends on a state change", () => {
    const a = pushTimelineEntry(undefined, entry("routing"));
    const b = pushTimelineEntry(a, entry("route_ready"));
    expect(b.map((e) => e.state)).toEqual(["routing", "route_ready"]);
  });

  it("drops a repeat of the last entry (heartbeat)", () => {
    const a = pushTimelineEntry(undefined, entry("in_transit", "vehicle en route"));
    const b = pushTimelineEntry(a, entry("in_transit", "vehicle en route"));
    expect(b).toHaveLength(1);
  });

  it("appends a fresh detail line on the same state", () => {
    const a = pushTimelineEntry(undefined, entry("in_transit", "vehicle en route"));
    const b = pushTimelineEntry(a, entry("in_transit", "auto-reroute — road blocked ahead on B"));
    expect(b).toHaveLength(2);
    expect(b[1].detail).toContain("auto-reroute");
  });

  it("caps the log length", () => {
    let log: RequestTimelineEntry[] = [];
    for (let i = 0; i < 25; i++) log = pushTimelineEntry(log, entry("in_transit", `d${i}`, i));
    expect(log.length).toBeLessThanOrEqual(16);
    expect(log[log.length - 1].detail).toBe("d24");
  });
});
