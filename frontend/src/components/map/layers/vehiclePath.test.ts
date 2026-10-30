import { describe, expect, it } from "vitest";
import { roadEdges } from "@/data/network";
import { haversineMeters } from "@/utils/geo";
import { pathBetween, sampleAlong, edgeOf } from "./vehiclePath";

const edge = roadEdges.find((e) => e.path.length > 3 && e.lengthM > 80)!;
const at = (s: number) => sampleAlong(edge.path, s / edge.lengthM);

describe("pathBetween", () => {
  it("follows the road's bends between two fixes on the same edge", () => {
    const a = at(5);
    const b = at(edge.lengthM - 5);
    const path = pathBetween(
      { lng: a[0], lat: a[1], lane: edge.id },
      { lng: b[0], lat: b[1], lane: edge.id },
    );
    expect(path.length).toBeGreaterThan(2);
    for (const f of [0.25, 0.5, 0.75]) {
      const p = sampleAlong(path, f);
      const near = Math.min(...edge.path.map((v) => haversineMeters(v, p)));
      expect(near).toBeLessThan(edge.lengthM); // sanity
      const on = pathBetween({ lng: p[0], lat: p[1], lane: edge.id }, { lng: p[0], lat: p[1], lane: edge.id });
      expect(on.length).toBeGreaterThan(0);
    }
  });

  it("falls back to a straight line when a road is unknown or the fix is far off it", () => {
    expect(pathBetween({ lng: 1, lat: 2, lane: ":J1_0" }, { lng: 3, lat: 4, lane: "nope" })).toEqual([
      [1, 2],
      [3, 4],
    ]);
    const far = pathBetween(
      { lng: edge.path[0][0] + 0.01, lat: edge.path[0][1], lane: edge.id },
      { lng: edge.path[1][0], lat: edge.path[1][1], lane: edge.id },
    );
    expect(far).toHaveLength(2);
  });

  it("treats junction-internal lanes as no road", () => {
    expect(edgeOf(":cluster_1_0")).toBeNull();
    expect(edgeOf("123")).toBe("123");
  });
});

describe("sampleAlong", () => {
  it("returns the ends at 0 and 1 and the middle by distance", () => {
    const p: [number, number][] = [
      [0, 0],
      [0, 0.001],
      [0.001, 0.001],
    ];
    expect(sampleAlong(p, 0)).toEqual([0, 0]);
    expect(sampleAlong(p, 1)[0]).toBeCloseTo(0.001, 6);
    const mid = sampleAlong(p, 0.5);
    expect(mid[0]).toBeCloseTo(0, 5);
    expect(mid[1]).toBeCloseTo(0.001, 4);
  });
});
