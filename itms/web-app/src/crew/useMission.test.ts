import { describe, expect, it } from "vitest";
import type { EmergencyRequest } from "@/types";
import { requestForUnit, unitOptions } from "./useMission";

const req = (over: Partial<EmergencyRequest>): EmergencyRequest => ({
  id: "r",
  vehicleId: "EV-001",
  vehicleKind: "ambulance",
  state: "in_transit",
  sourceEdge: "a",
  destinationEdge: "b",
  alternatives: [],
  timeline: [],
  updatedAt: "2026-10-17T10:00:00Z",
  ...over,
});

describe("unitOptions", () => {
  it("offers every unit of the fleet, by call sign, even with no calls", () => {
    const fleet = [
      { unitId: "AMB-1", callSign: "Ambulance 1" },
      { unitId: "POL-2", callSign: "" },
    ];
    const names = unitOptions([], fleet).map((u) => u.name);
    expect(names).toEqual(["Ambulance 1", "Police 2"]);
  });

  it("lists only units that have had a call, named by what they are", () => {
    expect(unitOptions([])).toEqual([]);
    const options = unitOptions([
      req({ id: "a", vehicleId: "unit-police-3", vehicleKind: "police" }),
      req({ id: "b", vehicleId: "unit-ambulance-0", vehicleKind: "ambulance" }),
    ]);
    expect(options.map((u) => [u.name, u.kind])).toEqual([
      ["Ambulance 0", "ambulance"],
      ["Police 3", "police"],
    ]);
  });

  it("marks a unit with a live call as active and lists it first", () => {
    const options = unitOptions([req({ vehicleId: "EV-101" })]);
    expect(options[0]).toMatchObject({ id: "EV-101", active: true });
  });

  it("does not count a finished call, and adds units it has never heard of", () => {
    const options = unitOptions([req({ vehicleId: "EV-001", state: "completed" }), req({ id: "x", vehicleId: "amb-07" })]);
    expect(options.find((u) => u.id === "EV-001")!.active).toBe(false);
    expect(options.find((u) => u.id === "amb-07")).toMatchObject({ name: "Ambulance 7", active: true });
  });
});

describe("requestForUnit", () => {
  it("is null until a unit is chosen, or when it has no calls", () => {
    expect(requestForUnit([req({})], null)).toBeNull();
    expect(requestForUnit([req({})], "EV-999")).toBeNull();
  });

  it("prefers the live call over a finished one", () => {
    const done = req({ id: "old", state: "completed", updatedAt: "2026-10-17T11:00:00Z" });
    const live = req({ id: "now", updatedAt: "2026-10-17T09:00:00Z" });
    expect(requestForUnit([done, live], "EV-001")!.id).toBe("now");
  });

  it("falls back to the most recent finished call, so its summary can be shown", () => {
    const older = req({ id: "older", state: "completed", updatedAt: "2026-10-17T08:00:00Z" });
    const newer = req({ id: "newer", state: "cancelled", updatedAt: "2026-10-17T09:00:00Z" });
    expect(requestForUnit([older, newer], "EV-001")!.id).toBe("newer");
  });
});
