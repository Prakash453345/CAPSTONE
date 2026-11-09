import { describe, expect, it } from "vitest";
import { unitName } from "./words";

describe("unitName", () => {
  it.each([
    ["unit-police-3", "Police 3"],
    ["unit-ambulance-0", "Ambulance 0"],
    ["unit-fire_truck-12", "Fire truck 12"],
    ["fire-4", "Fire truck 4"],
    ["amb-07", "Ambulance 7"],
    ["amb01", "Ambulance 1"],
  ])("%s reads as %s", (id, name) => {
    expect(unitName(id)).toBe(name);
  });

  it("leaves an id it does not recognise as it is", () => {
    expect(unitName("EV-001")).toBe("EV-001");
  });
});
