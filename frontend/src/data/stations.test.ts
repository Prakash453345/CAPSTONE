import { describe, expect, it } from "vitest";
import { nearestRoadPoint, stations } from "@/data/stations";

describe("stations", () => {
  it("lists dispatch police stations and the fire station, not Cyber Crime", () => {
    const names = stations.map((s) => s.name);
    expect(names).toContain("Police Control Room");
    expect(names).toContain("Agni Mapaka Kendram");
    expect(names).not.toContain("Cyber Crime");
    expect(stations.filter((s) => s.kind === "fire_station")).toHaveLength(1);
  });

  it("puts every station on a road, and says how far off the building is", () => {
    const control = stations.find((s) => s.name === "Police Control Room")!;
    expect(control.offRoadM).toBeLessThan(100);
    expect(nearestRoadPoint(control.lat, control.lon)!.at).toEqual(control.at);
  });
});
