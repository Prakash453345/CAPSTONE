import { describe, expect, it } from "vitest";
import {
  classifyAnomalyEvent,
  classifyConnectionEvent,
  classifyCorridorEvent,
  classifyEmergencyEvent,
  classifySignalFault,
  type EmergencyTransition,
} from "@/services/traffic/notifications";
import type { Anomaly } from "@/types";

function anomaly(over: Partial<Anomaly> = {}): Anomaly {
  return {
    id: "an-1",
    source: "operator",
    kind: "lane_blockage",
    severity: "medium",
    status: "active",
    edgeId: "E1",
    estimatedImpact: 0.5,
    startTime: new Date().toISOString(),
    ...over,
  };
}

function transition(over: Partial<EmergencyTransition> = {}): EmergencyTransition {
  return {
    requestId: "req-1",
    vehicleId: "amb-1",
    vehicleKind: "ambulance",
    prevState: undefined,
    nextState: "route_ready",
    prevDetail: "",
    detail: "",
    actor: "system:router",
    ...over,
  };
}

describe("classifyAnomalyEvent", () => {
  it("fires anomaly-created the first time an anomaly is seen active", () => {
    const n = classifyAnomalyEvent(undefined, anomaly({ status: "active" }), 1000);
    expect(n?.kind).toBe("anomaly-created");
    expect(n?.anomalyId).toBe("an-1");
  });

  it("scales tone with severity", () => {
    expect(classifyAnomalyEvent(undefined, anomaly({ severity: "low" }), 1)?.tone).toBe("info");
    expect(classifyAnomalyEvent(undefined, anomaly({ severity: "medium" }), 1)?.tone).toBe("warn");
    expect(classifyAnomalyEvent(undefined, anomaly({ severity: "high" }), 1)?.tone).toBe("critical");
    expect(classifyAnomalyEvent(undefined, anomaly({ severity: "blocked" }), 1)?.tone).toBe(
      "critical",
    );
  });

  it("fires anomaly-cleared when a previously-active anomaly stops being active", () => {
    const n = classifyAnomalyEvent("active", anomaly({ status: "resolved" }), 2000);
    expect(n?.kind).toBe("anomaly-cleared");
    expect(n?.tone).toBe("ok");
  });

  it("does not fire on a repeat update that leaves status unchanged", () => {
    expect(classifyAnomalyEvent("active", anomaly({ status: "active" }), 1)).toBeNull();
    expect(classifyAnomalyEvent("resolved", anomaly({ status: "resolved" }), 1)).toBeNull();
  });
});

describe("classifyEmergencyEvent", () => {
  it("does not fire on the heartbeat republish (state and detail both unchanged)", () => {
    const n = classifyEmergencyEvent(
      transition({ prevState: "in_transit", nextState: "in_transit", prevDetail: "", detail: "" }),
      1,
    );
    expect(n).toBeNull();
  });

  it("fires route-calculated the first time a request reaches route_ready", () => {
    expect(
      classifyEmergencyEvent(transition({ prevState: undefined, nextState: "route_ready" }), 1)
        ?.kind,
    ).toBe("route-calculated");
    expect(
      classifyEmergencyEvent(transition({ prevState: "routing", nextState: "route_ready" }), 1)
        ?.kind,
    ).toBe("route-calculated");
  });

  it("fires route-recalculated for an operator-initiated reroute while still route_ready", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "route_ready",
        nextState: "route_ready",
        detail: "operator recalculated",
        actor: "operator:console",
      }),
      1,
    );
    expect(n?.kind).toBe("route-recalculated");
  });

  it("fires auto-reroute for a monitor-initiated reroute while still route_ready", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "route_ready",
        nextState: "route_ready",
        detail: "auto-reroute — blocked ahead",
        actor: "system:monitor",
      }),
      1,
    );
    expect(n?.kind).toBe("auto-reroute");
    expect(n?.message).toContain("blocked ahead");
  });

  it("does not fire for an unrecognised route_ready -> route_ready detail", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "route_ready",
        nextState: "route_ready",
        detail: "something else",
        actor: "system:monitor",
      }),
      1,
    );
    expect(n).toBeNull();
  });

  it("fires auto-reroute for an in-flight reroute (state unchanged)", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "in_transit",
        nextState: "in_transit",
        detail: "auto-reroute — anomaly ahead",
        actor: "system:monitor",
      }),
      1,
    );
    expect(n?.kind).toBe("auto-reroute");
  });

  it("fires road-blocked-ahead when an in-flight reroute attempt finds no path", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "in_transit",
        nextState: "in_transit",
        detail: "reroute held: destination isolated",
        actor: "system:monitor",
      }),
      1,
    );
    expect(n?.kind).toBe("road-blocked-ahead");
    expect(n?.message).toContain("destination isolated");
  });

  it("does not fire for an unrelated in-flight detail change", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "in_transit",
        nextState: "in_transit",
        detail: "vehicle en route",
        actor: "system:monitor",
      }),
      1,
    );
    expect(n).toBeNull();
  });

  it("fires route-failure for a system-initiated cancellation", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "routing",
        nextState: "cancelled",
        detail: "destination isolated",
        actor: "system:router",
      }),
      1,
    );
    expect(n?.kind).toBe("route-failure");
    expect(n?.tone).toBe("critical");
  });

  it("does not fire for an operator-initiated cancellation", () => {
    const n = classifyEmergencyEvent(
      transition({ prevState: "route_ready", nextState: "cancelled", actor: "operator:console" }),
      1,
    );
    expect(n).toBeNull();
  });

  it("fires emergency-vehicle-arrived on completion", () => {
    const n = classifyEmergencyEvent(
      transition({ prevState: "in_transit", nextState: "completed", actor: "system:monitor" }),
      1,
    );
    expect(n?.kind).toBe("emergency-vehicle-arrived");
    expect(n?.tone).toBe("ok");
  });

  it("does not fire for an uninteresting transition (e.g. corridor activation)", () => {
    const n = classifyEmergencyEvent(
      transition({
        prevState: "route_ready",
        nextState: "green_corridor_active",
        actor: "operator:console",
      }),
      1,
    );
    expect(n).toBeNull();
  });
});

describe("classifyCorridorEvent", () => {
  it("fires corridor-activated", () => {
    const n = classifyCorridorEvent(
      { requestId: "req-1", corridorId: "gc-1", event: "activated" },
      1,
    );
    expect(n?.kind).toBe("corridor-activated");
    expect(n?.requestId).toBe("req-1");
  });

  it("fires junction-passed with the junction id, named via shortJunctionName", () => {
    const n = classifyCorridorEvent(
      { requestId: "req-1", corridorId: "gc-1", event: "junction_passed", junctionId: "1880441505" },
      1,
    );
    expect(n?.kind).toBe("junction-passed");
    expect(n?.intersectionId).toBe("1880441505");
    expect(n?.message).toContain("MG Road at Eat Street");
  });

  it("does not fire for junction_passed without a junction id", () => {
    expect(
      classifyCorridorEvent({ requestId: "req-1", corridorId: "gc-1", event: "junction_passed" }, 1),
    ).toBeNull();
  });

  it("does not fire for proposed or terminated", () => {
    expect(
      classifyCorridorEvent({ requestId: "req-1", corridorId: "gc-1", event: "proposed" }, 1),
    ).toBeNull();
    expect(
      classifyCorridorEvent({ requestId: "req-1", corridorId: "gc-1", event: "terminated" }, 1),
    ).toBeNull();
  });
});

describe("classifySignalFault", () => {
  it("labels a known fault type", () => {
    const n = classifySignalFault(
      { intersectionId: "1880441505", faultType: "comms_lost", detail: "" },
      1,
    );
    expect(n.kind).toBe("signal-fault");
    expect(n.tone).toBe("critical");
    expect(n.message).toContain("communication lost");
    expect(n.intersectionId).toBe("1880441505");
  });

  it("falls back to the raw fault type when unrecognised", () => {
    const n = classifySignalFault(
      { intersectionId: "1880441505", faultType: "mystery_fault", detail: "" },
      1,
    );
    expect(n.message).toContain("mystery_fault");
  });
});

describe("classifyConnectionEvent", () => {
  it("fires connection-lost when a live connection drops", () => {
    const n = classifyConnectionEvent("online", "reconnecting", true, 1);
    expect(n?.kind).toBe("connection-lost");
  });

  it("fires connection-restored after a real outage", () => {
    expect(classifyConnectionEvent("reconnecting", "online", true, 1)?.kind).toBe(
      "connection-restored",
    );
    expect(classifyConnectionEvent("offline", "online", true, 1)?.kind).toBe(
      "connection-restored",
    );
  });

  it("does not report the first cold connect as a recovery", () => {
    expect(classifyConnectionEvent("connecting", "online", false, 1)).toBeNull();
  });

  it("does not fire when status is unchanged", () => {
    expect(classifyConnectionEvent("online", "online", true, 1)).toBeNull();
  });
});
