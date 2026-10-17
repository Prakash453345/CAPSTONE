import { describe, expect, it } from "vitest";
import { edgeById, junctions, signalJunctions, roadEdges } from "@/data/network";
import { haversineMeters } from "@/utils/geo";
import {
  buildPlan,
  formatDistance,
  maneuverAfter,
  nextManeuver,
  orientedPaths,
  projectOnPlan,
  roadPhrase,
  type RoutePlan,
} from "./plan";

/** A walk along connected edges, so a test route is a real chain on the bundled network.
 *  It follows where the last edge actually ended, whichever way round it was driven. */
function walk(start: string, steps: number): string[] {
  const first = edgeById.get(start)!;
  const ids = [start];
  let end = first.path.at(-1)!;
  for (let i = 0; i < steps; i++) {
    const next = roadEdges.find(
      (e) =>
        !ids.includes(e.id) &&
        (haversineMeters(end, e.path[0]!) < 45 || haversineMeters(end, e.path.at(-1)!) < 45),
    );
    if (!next) break;
    ids.push(next.id);
    end = haversineMeters(end, next.path[0]!) <= haversineMeters(end, next.path.at(-1)!) ? next.path.at(-1)! : next.path[0]!;
  }
  return ids;
}

const chain = (() => {
  for (const e of roadEdges) {
    const ids = walk(e.id, 6);
    if (ids.length >= 5) return ids;
  }
  throw new Error("no chain of connected edges in the test network");
})();

describe("orientedPaths", () => {
  it("joins edges end to start whichever way the network stores them", () => {
    const parts = orientedPaths(chain);
    expect(parts).toHaveLength(chain.length);
    for (let i = 1; i < parts.length; i++) {
      const gap = haversineMeters(parts[i - 1]!.path.at(-1)!, parts[i]!.path[0]!);
      expect(gap).toBeLessThan(60);
    }
  });

  it("skips edges that are not in the network", () => {
    expect(orientedPaths(["nope", chain[0]!])).toHaveLength(1);
    expect(orientedPaths(["nope"])).toEqual([]);
  });
});

describe("buildPlan", () => {
  const plan = buildPlan(chain, signalJunctions.map((j) => j.id))!;

  it("returns null for a route with nothing on the map", () => {
    expect(buildPlan(["missing"])).toBeNull();
  });

  it("makes one continuous line with abutting spans", () => {
    expect(plan.totalM).toBeGreaterThan(0);
    expect(plan.spans[0]!.startM).toBe(0);
    expect(plan.spans.at(-1)!.endM).toBeCloseTo(plan.totalM, 3);
    for (let i = 1; i < plan.spans.length; i++) expect(plan.spans[i]!.startM).toBeCloseTo(plan.spans[i - 1]!.endM, 3);
    // within a few percent of the sum of the edges (connectors add a little)
    const sum = chain.reduce((n, id) => n + edgeById.get(id)!.lengthM, 0);
    expect(plan.totalM).toBeGreaterThan(sum * 0.95);
    expect(plan.totalM).toBeLessThan(sum * 1.4);
  });

  it("starts with a depart and ends with an arrival, in order", () => {
    expect(plan.maneuvers[0]!.kind).toBe("depart");
    expect(plan.maneuvers.at(-1)!.kind).toBe("arrive");
    expect(plan.maneuvers.at(-1)!.atM).toBeCloseTo(plan.totalM, 3);
    const at = plan.maneuvers.map((m) => m.atM);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    for (const m of plan.maneuvers) expect(m.text.length).toBeGreaterThan(3);
  });

  it("finds only signals that sit on the route, in route order", () => {
    const at = plan.signals.map((s) => s.atM);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    for (const s of plan.signals) {
      const j = junctions.find((x) => x.id === s.junctionId)!;
      expect(projectOnPlan(plan, [j.lng, j.lat]).offRouteM).toBeLessThanOrEqual(60);
    }
  });
});

describe("projectOnPlan", () => {
  const plan = buildPlan(chain)!;

  it("puts a point on the route at the right distance, with no offset", () => {
    for (const f of [0, 0.3, 0.7, 1]) {
      const d = plan.totalM * f;
      const j = (() => {
        // the vertex nearest d
        let i = 0;
        while (i < plan.cum.length - 1 && plan.cum[i]! < d) i++;
        return i;
      })();
      const hit = projectOnPlan(plan, plan.coords[j]!);
      expect(hit.offRouteM).toBeLessThan(0.5);
      expect(hit.alongM).toBeCloseTo(plan.cum[j]!, 0);
    }
  });

  it("reports how far off the route a point is", () => {
    const p = plan.coords[Math.floor(plan.coords.length / 2)]!;
    const off = projectOnPlan(plan, [p[0] + 0.01, p[1] + 0.01]);
    expect(off.offRouteM).toBeGreaterThan(50);
  });

  it("only searches the window when given one", () => {
    const end = plan.coords.at(-1)!;
    const inWindow = projectOnPlan(plan, end, { fromM: 0, toM: plan.totalM * 0.1 });
    expect(inWindow.alongM).toBeLessThan(plan.totalM * 0.2);
  });
});

describe("next maneuver", () => {
  const plan: RoutePlan = {
    edgeIds: ["a", "b", "c"],
    coords: [],
    cum: [],
    totalM: 1000,
    spans: [],
    signals: [],
    maneuvers: [
      { id: "d", atM: 0, kind: "depart", side: "straight", sharp: false, road: "A", text: "Start" },
      { id: "1", atM: 300, kind: "turn", side: "left", sharp: false, road: "B", text: "Turn left onto B" },
      { id: "2", atM: 700, kind: "turn", side: "right", sharp: false, road: "C", text: "Turn right onto C" },
      { id: "z", atM: 1000, kind: "arrive", side: "straight", sharp: false, road: "C", text: "Arrive" },
    ],
  };

  it("never offers the depart, and moves on once a turn is behind you", () => {
    expect(nextManeuver(plan, 0).id).toBe("1");
    expect(nextManeuver(plan, 290).id).toBe("1");
    expect(nextManeuver(plan, 305).id).toBe("2");
    expect(nextManeuver(plan, 990).id).toBe("z");
    expect(nextManeuver(plan, 5000).id).toBe("z");
  });

  it("gives the maneuver after, until the arrival", () => {
    expect(maneuverAfter(plan, plan.maneuvers[1]!)!.id).toBe("2");
    expect(maneuverAfter(plan, plan.maneuvers[3]!)).toBeNull();
  });
});

describe("wording", () => {
  it("talks about unnamed roads by their class", () => {
    expect(roadPhrase("Primary road")).toBe("the primary road");
    expect(roadPhrase("Service road")).toBe("the service road");
    expect(roadPhrase("MG Road")).toBe("MG Road");
  });

  it("rounds distances the way a driver says them", () => {
    expect(formatDistance(0)).toBe("0 m");
    expect(formatDistance(47)).toBe("50 m");
    expect(formatDistance(310)).toBe("310 m");
    expect(formatDistance(1240)).toBe("1.2 km");
    expect(formatDistance(12_400)).toBe("12 km");
    expect(formatDistance(Number.NaN)).toBe("–");
  });
});
