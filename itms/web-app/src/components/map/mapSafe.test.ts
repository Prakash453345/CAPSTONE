import { describe, expect, it } from "vitest";
import { isMapAlive } from "@/components/map/mapSafe";
import type { Map as MapLibreMap } from "maplibre-gl";

function fakeMap(removed: boolean): MapLibreMap {
  return { _removed: removed } as unknown as MapLibreMap;
}

describe("isMapAlive", () => {
  it("is true for a map that hasn't been removed", () => {
    expect(isMapAlive(fakeMap(false))).toBe(true);
  });

  it("is false once _removed is set", () => {
    expect(isMapAlive(fakeMap(true))).toBe(false);
  });

  it("is false rather than throwing if the check itself blows up", () => {
    const cursed = {
      get _removed(): boolean {
        throw new Error("nope");
      },
    } as unknown as MapLibreMap;
    expect(isMapAlive(cursed)).toBe(false);
  });
});
