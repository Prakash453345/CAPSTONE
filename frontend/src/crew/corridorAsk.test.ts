import { describe, expect, it } from "vitest";
import { canAskCorridor, isCorridorAsk } from "@/crew/corridorAsk";

describe("corridor requests", () => {
  it("recognises a crew's request only while it waits for an operator", () => {
    const detail = "Crew asked for a green corridor. Reason: pursuit.";
    expect(isCorridorAsk({ state: "route_ready", detail })).toBe(true);
    expect(isCorridorAsk({ state: "green_corridor_active", detail })).toBe(false);
    expect(isCorridorAsk({ state: "route_ready", detail: "Route planned" })).toBe(false);
    expect(isCorridorAsk({ state: "route_ready" })).toBe(false);
  });

  it("lets police crews ask, not ambulances or fire trucks", () => {
    expect(canAskCorridor("police")).toBe(true);
    expect(canAskCorridor("fire_truck")).toBe(false);
    expect(canAskCorridor("ambulance")).toBe(false);
    expect(canAskCorridor(undefined)).toBe(false);
  });
});
