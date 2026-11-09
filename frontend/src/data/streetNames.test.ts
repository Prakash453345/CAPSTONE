import { describe, it, expect } from "vitest";
import streetNames from "./street-names.json";
import { ROAD_NAMES } from "./roadNames";
import { roadEdges, routeLabel } from "./network";

const streets = streetNames as Record<string, Record<string, { n?: string; a?: string }>>;

describe("generated street names (scripts/street-names.mjs)", () => {
  it("gives every listed segment a street or an area, never an empty entry", () => {
    for (const city of Object.keys(streets)) {
      for (const entry of Object.values(streets[city]!)) {
        expect(Boolean(entry.n || entry.a)).toBe(true);
      }
    }
  });

  it("agrees with the hand-checked corridor names wherever it found a street", () => {
    const checked = Object.entries(ROAD_NAMES).filter(([id]) => streets.vijayawada?.[id]?.n);
    const agree = checked.filter(([id, name]) => streets.vijayawada![id]!.n === name);
    expect(checked.length).toBeGreaterThan(20);
    // one segment ends where two named streets meet; the hand-checked name wins there
    expect(agree.length).toBeGreaterThanOrEqual(checked.length - 1);
  });

  it("names the Amaravati capital grid roads", () => {
    const names = new Set(Object.values(streets.amaravati ?? {}).map((e) => e.n));
    for (const road of ["Seed Access Road", "E8", "N9"]) expect(names.has(road)).toBe(true);
  });
});

describe("routeLabel", () => {
  it("says 'Along' for a trip on one street and 'to' between two", () => {
    const mg = roadEdges.filter((e) => e.name === "MG Road");
    const eat = roadEdges.find((e) => e.name === "Eat Street");
    expect(mg.length).toBeGreaterThan(1);
    expect(routeLabel(mg[0]!.id, mg[1]!.id)).toBe("Along MG Road");
    expect(routeLabel(mg[0]!.id, eat!.id)).toBe("MG Road to Eat Street");
  });
});
