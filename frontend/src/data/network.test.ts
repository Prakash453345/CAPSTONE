import { describe, it, expect } from "vitest";
import {
  roadEdges,
  signalJunctions,
  edgeById,
  junctionById,
  nearestEdge,
  networkKind,
  shortJunctionName,
} from "./network";

describe("SUMO network adapter", () => {
  it.runIf(networkKind === "corridor")(
    "loads the real exported corridor, including existing emergency fixture IDs",
    () => {
      expect(roadEdges).toHaveLength(33);
      expect(signalJunctions).toHaveLength(7);
      expect(edgeById.has("-177626285")).toBe(true);
      // named after the streets that meet there, from the OSM name lookup
      expect(shortJunctionName("1880441505")).toBe("MG Road at Eat Street");
      expect(edgeById.get("-177626285")?.name).toBe("Eat Street");
    },
  );
  it.runIf(networkKind === "district")("loads the district grid", () => {
    expect(roadEdges).toHaveLength(314);
    expect(signalJunctions).toHaveLength(17);
    expect(roadEdges.filter((e) => e.name === "MG Road").length).toBeGreaterThan(5);
  });
  it("every road has real geometry and ids are unique", () => {
    expect(edgeById.size).toBe(roadEdges.length);
    for (const e of roadEdges) {
      expect(e.path.length).toBeGreaterThan(1);
      expect(e.lengthM).toBeGreaterThan(0);
    }
    for (const j of signalJunctions) expect(junctionById.get(j.id)).toBe(j);
  });
  it("snaps an actual point to a road and rejects an off-network target", () => {
    const edge = roadEdges[0];
    expect(nearestEdge(edge.path[0], 1)?.distanceM).toBeLessThan(0.01);
    expect(nearestEdge([0, 0])).toBeNull();
    expect(nearestEdge([NaN, NaN])).toBeNull();
  });
});
