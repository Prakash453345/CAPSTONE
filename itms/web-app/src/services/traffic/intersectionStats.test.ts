import { describe, expect, it } from "vitest";
import { junctionVehicleStats } from "@/services/traffic/intersectionStats";
import type { Vehicle } from "@/types";

const JUNCTION: [number, number] = [80.6335, 16.5062];

function veh(over: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "v1",
    type: "car",
    latitude: 16.5062,
    longitude: 80.6335,
    speed: 20,
    heading: 0,
    timestamp: new Date().toISOString(),
    ...over,
  };
}

describe("junctionVehicleStats", () => {
  it("counts only vehicles within the junction radius", () => {
    const near = veh({ id: "near" }); // at the junction itself
    const far = veh({ id: "far", latitude: 16.6, longitude: 80.7 }); // far away
    const stats = junctionVehicleStats(JUNCTION, [near, far]);
    expect(stats.vehicleCount).toBe(1);
  });

  it("averages speed over nearby vehicles only", () => {
    const a = veh({ id: "a", speed: 10 });
    const b = veh({ id: "b", speed: 30 });
    const far = veh({ id: "far", latitude: 16.6, longitude: 80.7, speed: 100 });
    const stats = junctionVehicleStats(JUNCTION, [a, b, far]);
    expect(stats.averageSpeed).toBe(20);
  });

  it("counts a nearby vehicle under the queue-speed threshold as queued", () => {
    const slow = veh({ id: "slow", speed: 3 });
    const fast = veh({ id: "fast", speed: 40 });
    const stats = junctionVehicleStats(JUNCTION, [slow, fast]);
    expect(stats.queueLength).toBe(1);
  });

  it("returns zeroed stats with no nearby vehicles", () => {
    expect(junctionVehicleStats(JUNCTION, [])).toEqual({
      queueLength: 0,
      averageSpeed: 0,
      vehicleCount: 0,
    });
  });
});
