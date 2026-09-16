import { describe, it, expect } from "vitest";
import {
  roadEdges,
  signalJunctions,
  edgeById,
  nearestEdge,
  shortJunctionName,
} from "./network";

describe("SUMO network adapter", () => {
  it("loads the real exported corridor, including existing emergency fixture IDs", () => {
    expect(roadEdges).toHaveLength(33);
    expect(signalJunctions).toHaveLength(7);
    expect(edgeById.has("-177626285")).toBe(true);
    expect(shortJunctionName("1880441505")).toBe("Junction 1505");
    for (const e of roadEdges) {
      expect(e.path.length).toBeGreaterThan(1);
      expect(e.lengthM).toBeGreaterThan(0);
    }
  });
  it("snaps an actual point to a road and rejects an off-network target", () => {
    const edge = roadEdges[0];
    expect(nearestEdge(edge.path[0], 1)?.distanceM).toBeLessThan(0.01);
    expect(nearestEdge([0, 0])).toBeNull();
    expect(nearestEdge([NaN, NaN])).toBeNull();
  });
});
