import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWebSocketProvider } from "./wsProvider";
import type { TrafficSnapshot } from "./types";

class Socket {
  static OPEN = 1;
  static latest: Socket;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    Socket.latest = this;
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  sendEvent(event_type: string, payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify({ event_type, payload }) });
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal("location", { protocol: "http:", host: "localhost" });
  vi.stubGlobal("WebSocket", Socket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("live snapshot integration", () => {
  it("seeds incidents raised before the page opened from the registry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => [{ incident_id: "old-1", intersection_id: "1880441505", state: "candidate",
        first_seen_ms: Date.now() - 60_000, fused_probability: 0.9 }],
    })));
    const provider = createWebSocketProvider();
    let snap: TrafficSnapshot | undefined;
    provider.subscribe((s) => {
      snap = s;
    });
    provider.start();
    Socket.latest.onopen?.();
    await vi.advanceTimersByTimeAsync(500);
    expect(snap!.incidents.map((i) => [i.id, i.status])).toEqual([["old-1", "candidate"]]);
    provider.stop();
  });
  it("keeps a corridor that arrives before its request (topics are relayed independently)", () => {
    const provider = createWebSocketProvider();
    let snap: TrafficSnapshot | undefined;
    provider.subscribe((s) => {
      snap = s;
    });
    provider.start();
    Socket.latest.onopen?.();
    const corridor = (event: string, detail = "") => ({
      corridor_id: "gc-0003", request_id: "r1", vehicle_id: "EV-AMB-1", event, status: "ACTIVE",
      route_edges: ["a", "b"], peak_concurrency: 1, detail,
      reservations: [{ intersection_id: "J1", movements: ["L0"], open_at_ms: 0, close_at_ms: 1, order: 0 }],
    });
    Socket.latest.sendEvent("GreenCorridorUpdated", corridor("activated"));
    Socket.latest.sendEvent("GreenCorridorUpdated", corridor("junction_passed", "J1"));
    Socket.latest.sendEvent("EmergencyRequestUpdated", {
      request_id: "r1", vehicle_id: "EV-AMB-1", vehicle_kind: "AMBULANCE",
      state: "GREEN_CORRIDOR_ACTIVE", source_edge: "a", destination_edge: "b",
    });
    vi.advanceTimersByTime(500);
    const req = snap!.emergencyRequests.find((r) => r.id === "r1");
    expect(req?.corridor?.corridorId).toBe("gc-0003");
    expect(req?.corridor?.reservations).toHaveLength(1);
    expect(req?.corridor?.passedIntersections).toEqual(["J1"]);
    provider.stop();
  });
  it("does not report socket-open or timer ticks as fresh traffic", () => {
    const provider = createWebSocketProvider();
    let snap: TrafficSnapshot | undefined;
    provider.subscribe((s) => {
      snap = s;
    });
    provider.start();
    Socket.latest.onopen?.();
    vi.advanceTimersByTime(500);
    expect(snap!.summary.lastUpdate).toBeNull();
    expect(snap!.summary.operational).toBe(false);
    Socket.latest.sendEvent("ApproachState", {
      movement_id: "-177626285",
      occupancy: 0.4,
    });
    vi.advanceTimersByTime(500);
    const last = snap!.summary.lastUpdate;
    expect(snap!.roadCongestion["-177626285"]).toBe(0.4);
    expect(snap!.summary.operational).toBe(true);
    vi.advanceTimersByTime(7000);
    expect(snap!.summary.lastUpdate).toBe(last);
    expect(snap!.summary.operational).toBe(false);
    provider.stop();
  });
  it("handles malformed frames and threads detector lifecycle through snapshots", () => {
    const provider = createWebSocketProvider();
    let snap: TrafficSnapshot | undefined;
    provider.subscribe((s) => {
      snap = s;
    });
    provider.start();
    Socket.latest.onopen?.();
    Socket.latest.onmessage?.({ data: "null" });
    Socket.latest.onmessage?.({ data: "not json" });
    Socket.latest.sendEvent("VehiclePositionUpdated", {
      vehicle_id: "bad",
      lat: null,
    });
    Socket.latest.sendEvent("IncidentCandidate", {
      incident_id: "i1",
      intersection_id: "1880441505",
      detected_at: Date.now(),
      fused_probability: 0.85,
    });
    vi.advanceTimersByTime(500);
    expect(snap!.incidents[0].status).toBe("candidate");
    expect(snap!.vehicles).toHaveLength(0);
    Socket.latest.sendEvent("IncidentUpdated", {
      incident_id: "i1",
      new_state: "REJECTED",
    });
    vi.advanceTimersByTime(500);
    expect(snap!.incidents[0].status).toBe("resolved");
    provider.stop();
  });
  it("forgets a live request the backend stopped announcing, but only while the stream flows", () => {
    const provider = createWebSocketProvider();
    let snap: TrafficSnapshot | undefined;
    provider.subscribe((s) => {
      snap = s;
    });
    provider.start();
    Socket.latest.onopen?.();
    const request = (id: string) =>
      Socket.latest.sendEvent("EmergencyRequestUpdated", {
        request_id: id,
        vehicle_id: `v-${id}`,
        vehicle_kind: "AMBULANCE",
        state: "ROUTE_READY",
        source_edge: "-177626285",
        destination_edge: "-679017002",
        updated_at: Date.now(),
      });
    const ids = () => snap!.emergencyRequests.map((r) => r.id).sort();
    request("old");
    request("live");
    vi.advanceTimersByTime(500);
    expect(ids()).toEqual(["live", "old"]);

    // the stream goes quiet (connection trouble): nothing is forgotten
    vi.advanceTimersByTime(60_000);
    expect(ids()).toEqual(["live", "old"]);

    // the stream flows again, re-announcing only "live" every 10 s
    for (let t = 0; t < 50_000; t += 10_000) {
      request("live");
      vi.advanceTimersByTime(10_000);
    }
    request("live");
    vi.advanceTimersByTime(500);
    expect(ids()).toEqual(["live"]);
    provider.stop();
  });
});
