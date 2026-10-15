import { describe, expect, it } from "vitest";
import type { LineString, Point } from "geojson";
import rawVijayawada from "../../../scenarios/networks/vijayawada/vijayawada_corridor.geojson?raw";
import rawAmaravati from "../../../scenarios/generated/amaravati_v2/amaravati_v2.geojson?raw";
import { CITIES, citiesFor, formatLatLng } from "@/data/city";
import { networkFor, roadClassName } from "@/data/network";

describe("citiesFor (VITE_CITY)", () => {
  it("shows both cities when unset, empty, all or unknown", () => {
    for (const v of [undefined, "", "all", "both", "berlin"]) expect(citiesFor(v)).toBe(CITIES);
  });
  it("narrows to the named city, any case", () => {
    expect(citiesFor(" Amaravati ").map((c) => c.id)).toEqual(["amaravati"]);
    expect(citiesFor("vijayawada").map((c) => c.id)).toEqual(["vijayawada"]);
    expect(citiesFor("amaravati,vijayawada").map((c) => c.id)).toEqual(["vijayawada", "amaravati"]);
  });
  it("formats a centre as the globe shows it", () => {
    expect(formatLatLng(CITIES[0].center)).toBe("16.5062° N · 80.6335° E");
  });
});

describe("roadClassName", () => {
  it("names an unnamed OSM road by its class", () => {
    expect(roadClassName("highway.primary")).toBe("Primary road");
    expect(roadClassName("highway.trunk_link")).toBe("Trunk road link");
    expect(roadClassName("highway.residential")).toBeNull();
    expect(roadClassName(undefined)).toBeNull();
  });
});

describe("both cities on one map", () => {
  const parts = [
    { city: "vijayawada" as const, raw: rawVijayawada },
    { city: "amaravati" as const, raw: rawAmaravati },
  ];
  const both = networkFor(parts);
  const of = (city: string, kind: string) =>
    both.features.filter((f) => f.properties?.city === city && f.properties?.kind === kind);

  it("keeps every feature, tagged with its city, ids unique", () => {
    const one = (i: number) => networkFor([parts[i]]).features.length;
    expect(both.features.length).toBe(one(0) + one(1));
    const ids = both.features
      .filter((f) => f.properties?.kind === "edge")
      .map((f) => String(f.properties?.edge_id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("places Amaravati on Amaravati, its 121 signals included", () => {
    const pts = of("amaravati", "edge").flatMap((f) => (f.geometry as LineString).coordinates);
    for (const [lng, lat] of pts) {
      expect(lat).toBeGreaterThan(16.4);
      expect(lat).toBeLessThan(16.6);
      expect(lng).toBeGreaterThan(80.4);
      expect(lng).toBeLessThan(80.6);
    }
    expect(of("amaravati", "junction").filter((j) => j.properties?.is_traffic_light).length).toBe(121);
  });

  it("puts every Amaravati junction on its roads (four were at y = 0 in the network)", () => {
    for (const j of of("amaravati", "junction")) {
      const [lng, lat] = (j.geometry as Point).coordinates;
      expect(lat).toBeGreaterThan(16.4);
      expect(lat).toBeLessThan(16.6);
      expect(lng).toBeGreaterThan(80.4);
      expect(lng).toBeLessThan(80.6);
    }
  });
});
