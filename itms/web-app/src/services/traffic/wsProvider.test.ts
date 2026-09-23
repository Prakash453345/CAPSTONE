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
});
