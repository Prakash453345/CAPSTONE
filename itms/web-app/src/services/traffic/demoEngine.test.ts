import { beforeEach, describe, expect, it } from "vitest";
import { roadEdges } from "@/data/network";
import { useCrewStore } from "@/store/crewStore";
import { CommandError } from "@/services/traffic/commands";
import { createDemoEngine } from "@/services/traffic/demoEngine";

const edge = roadEdges[10]!.id;

function setup() {
  let t = 1_000_000;
  const engine = createDemoEngine(() => t);
  engine.start();
  /** Advance simulated time in 1 s ticks, collecting everything emitted. */
  const run = (seconds: number) => {
    let last = engine.tick();
    const events = [...last.events];
    for (let i = 0; i < seconds; i++) {
      t += 1000;
      last = engine.tick();
      events.push(...last.events);
    }
    return { ...last, events };
  };
  return { engine, run };
}

const anomalyCmd = (over: Record<string, unknown> = {}) => ({
  event_type: "AnomalyCreateRequested",
  payload: { anomaly_id: "a1", edge_id: edge, anomaly_type: "LANE_BLOCKAGE", severity: "BLOCKED", duration_s: null, ...over },
});

beforeEach(() => useCrewStore.setState({ offers: {}, calls: {}, hospital: {}, fleet: [] }));

describe("demo engine: anomalies", () => {
  it("creates, slows traffic, notifies and clears", () => {
    const { engine, run } = setup();
    engine.handle(anomalyCmd({ anomaly_type: "HEAVY_CONGESTION" }));
    const created = run(0);
    expect(created.anomalies).toMatchObject([{ id: "a1", status: "active", source: "operator" }]);
    expect(created.events.map((e) => e.kind)).toContain("anomaly-created");
    expect(engine.speedFactor(edge)).toBeLessThan(0.2);
    expect(engine.congestion(edge)).toBe(1);

    engine.handle({ event_type: "AnomalyClearRequested", payload: { anomaly_id: "a1", resolution: "RESOLVED" } });
    const cleared = run(0);
    expect(cleared.anomalies[0]!.status).toBe("resolved");
    expect(cleared.events.map((e) => e.kind)).toContain("anomaly-cleared");
    expect(engine.speedFactor(edge)).toBe(1);
  });

  it("auto-clears a time-boxed anomaly", () => {
    const { engine, run } = setup();
    engine.handle(anomalyCmd({ anomaly_type: "HEAVY_CONGESTION", duration_s: 5 }));
    expect(run(6).anomalies[0]!.status).toBe("resolved");
  });

  it("rejects unknown roads and anomalies", () => {
    const { engine } = setup();
    expect(() => engine.handle(anomalyCmd({ edge_id: "nope" }))).toThrow(CommandError);
    expect(() =>
      engine.handle({ event_type: "AnomalyClearRequested", payload: { anomaly_id: "ghost" } }),
    ).toThrow(CommandError);
  });
});

describe("demo engine: dispatch", () => {
  const call = (kind: string, id = "r1") => ({
    event_type: "EmergencyRequestCreated",
    payload: { request_id: id, vehicle_id: "", vehicle_kind: kind, source_edge: edge, destination_edge: edge },
  });

  it("offers the call, takes the crew's decline to the next unit, then runs the mission to completion", () => {
    const { engine, run } = setup();
    engine.handle(call("POLICE"));
    const first = Object.values(useCrewStore.getState().offers);
    expect(first).toHaveLength(1);

    engine.handle({ event_type: "CrewOfferResponse", payload: { offer_id: first[0]!.offerId, accept: false } });
    const second = Object.values(useCrewStore.getState().offers);
    expect(second).toHaveLength(1);
    expect(second[0]!.unitId).not.toBe(first[0]!.unitId);

    const states = new Set<string>();
    let result = run(0);
    for (let i = 0; i < 400 && result.requests.at(-1)?.state !== "completed"; i++) {
      result = run(1);
      for (const r of result.requests) states.add(r.state);
    }
    const req = result.requests[0]!;
    expect(req.state).toBe("completed");
    expect(req.vehicleId).toBe(second[0]!.unitId);
    expect(req.route?.edges.length).toBeGreaterThan(0);
    expect([...states]).toEqual(expect.arrayContaining(["routing", "route_ready", "green_corridor_active"]));
    expect(useCrewStore.getState().fleet.find((u) => u.unitId === req.vehicleId)?.busy).toBe(false);
  });

  it("reports an exhausted call when every crew of that kind has declined", () => {
    const { engine } = setup();
    engine.handle(call("FIRE_TRUCK"));
    const offer = Object.values(useCrewStore.getState().offers)[0]!;
    engine.handle({ event_type: "CrewOfferResponse", payload: { offer_id: offer.offerId, accept: false } });
    expect(useCrewStore.getState().calls.r1!.state).toBe("exhausted");
  });

  it("lets the operator cancel a mission", () => {
    const { engine, run } = setup();
    engine.handle(call("POLICE"));
    run(8);
    engine.handle({ event_type: "EmergencyCommand", payload: { request_id: "r1", action: "CANCEL" } });
    expect(run(0).requests[0]!.state).toBe("cancelled");
    expect(() =>
      engine.handle({ event_type: "EmergencyCommand", payload: { request_id: "r1", action: "RECALCULATE" } }),
    ).toThrow(CommandError);
  });

  it("sends an ambulance on to a hospital after the scene", () => {
    const { engine, run } = setup();
    engine.handle(call("AMBULANCE"));
    let result = run(0);
    for (let i = 0; i < 400 && !Object.keys(useCrewStore.getState().hospital).length; i++) result = run(1);
    const mission = Object.values(useCrewStore.getState().hospital)[0]!;
    expect(mission.state).toBe("at_scene");
    expect(mission.options.length).toBeGreaterThan(1);

    engine.handle({
      event_type: "CrewHospitalChoice",
      payload: { unit_id: mission.unitId, facility_id: mission.options[1]!.facilityId },
    });
    expect(useCrewStore.getState().hospital[mission.unitId]!.state).toBe("to_hospital");
    for (let i = 0; i < 600 && result.requests[0]!.state !== "completed"; i++) result = run(1);
    expect(result.requests[0]!.state).toBe("completed");
    expect(useCrewStore.getState().hospital[mission.unitId]!.state).toBe("done");
  });

  it("sends responders when an accident is reported", () => {
    const { engine } = setup();
    engine.handle(anomalyCmd({ anomaly_type: "ACCIDENT", severity: "HIGH" }));
    const kinds = Object.values(useCrewStore.getState().offers).map((o) => o.kind).sort();
    expect(kinds).toEqual(["ambulance", "fire_truck", "police"]);
  });
});
