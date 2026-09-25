import type {
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import type { ResolvedTheme } from "@/store/themeStore";

/**
 * Keyless basemap: OpenFreeMap's OpenMapTiles vector data (free, no key, no
 * request limits), recoloured to Google Maps' palette for each theme. Used
 * whenever no Google Map Tiles key is configured, so the dashboard looks the
 * same family either way.
 */
const SOURCE_STYLE = "https://tiles.openfreemap.org/styles/liberty";
export const OSM_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/" target="_blank">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>';

interface Palette {
  land: string;
  landAlt: string;
  park: string;
  water: string;
  waterLabel: string;
  building: string;
  buildingLine: string;
  road: string;
  roadCasing: string;
  arterial: string;
  arterialCasing: string;
  highway: string;
  highwayCasing: string;
  rail: string;
  boundary: string;
  label: string;
  labelStrong: string;
  halo: string;
}

// Sampled from Google Maps' default (light) and night (dark) renderings.
const PALETTE: Record<ResolvedTheme, Palette> = {
  light: {
    land: "#f5f5f5",
    landAlt: "#eef0f1",
    park: "#c8ebc4",
    water: "#9ccbf5",
    waterLabel: "#4a7fb5",
    building: "#e8eaed",
    buildingLine: "#dadce0",
    road: "#ffffff",
    roadCasing: "#dadce0",
    arterial: "#ffffff",
    arterialCasing: "#d2d5d9",
    highway: "#fde293",
    highwayCasing: "#f3c566",
    rail: "#d0d3d7",
    boundary: "#9aa0a6",
    label: "#5f6368",
    labelStrong: "#3c4043",
    halo: "#ffffff",
  },
  dark: {
    land: "#1f2124",
    landAlt: "#232528",
    park: "#1d2b23",
    water: "#0e1726",
    waterLabel: "#4e6d70",
    building: "#2a2c30",
    buildingLine: "#303236",
    road: "#3c4043",
    roadCasing: "#1f2124",
    arterial: "#46494d",
    arterialCasing: "#1f2124",
    highway: "#5f6368",
    highwayCasing: "#2a2c30",
    rail: "#35383c",
    boundary: "#5f6368",
    label: "#9aa0a6",
    labelStrong: "#e8eaed",
    halo: "#1f2124",
  },
};

let sourceStyle: Promise<StyleSpecification> | null = null;

function loadSourceStyle(): Promise<StyleSpecification> {
  sourceStyle ??= fetch(SOURCE_STYLE).then((r) => {
    if (!r.ok) throw new Error(`OpenFreeMap style ${r.status}`);
    return r.json() as Promise<StyleSpecification>;
  });
  sourceStyle.catch(() => {
    sourceStyle = null; // allow a retry on the next theme switch / mount
  });
  return sourceStyle;
}

const isMajor = (id: string) => /motorway|trunk_primary/.test(id);
const isArterial = (id: string) => /secondary_tertiary/.test(id);

/** One layer's paint, re-expressed in the Google palette. */
function recolour(layer: LayerSpecification, p: Palette): LayerSpecification | null {
  const id = layer.id;
  // Shaded relief and hatch patterns have no Google equivalent.
  if (id === "natural_earth" || id === "road_area_pattern" || id.endsWith("_hatching")) return null;
  if (id.startsWith("highway-shield") || id === "road_shield_us") return null;

  const paint = { ...(layer.paint ?? {}) } as Record<string, unknown>;
  const set = (k: string, v: unknown) => (paint[k] = v);

  switch (layer.type) {
    case "background":
      set("background-color", p.land);
      break;
    case "fill":
      if (/park|wood|grass|pitch|cemetery/.test(id)) set("fill-color", p.park);
      else if (/water/.test(id)) set("fill-color", p.water);
      else if (id === "building") {
        set("fill-color", p.building);
        set("fill-outline-color", p.buildingLine);
      } else if (/aeroway/.test(id)) set("fill-color", p.landAlt);
      else set("fill-color", p.landAlt);
      if (/outline/.test(id)) return null;
      delete paint["fill-pattern"];
      break;
    case "fill-extrusion":
      set("fill-extrusion-color", p.building);
      set("fill-extrusion-opacity", 0.85);
      break;
    case "line":
      if (/water/.test(id)) set("line-color", p.water);
      else if (/boundary/.test(id)) set("line-color", p.boundary);
      else if (/rail/.test(id)) set("line-color", p.rail);
      else if (/casing/.test(id)) {
        set(
          "line-color",
          isMajor(id) ? p.highwayCasing : isArterial(id) ? p.arterialCasing : p.roadCasing,
        );
      } else if (/aeroway/.test(id)) set("line-color", p.road);
      else if (/path|pedestrian/.test(id)) set("line-color", p.roadCasing);
      else if (/one_way/.test(id)) return null;
      else set("line-color", isMajor(id) ? p.highway : isArterial(id) ? p.arterial : p.road);
      break;
    case "symbol":
      if (/^poi_r(7|20)$/.test(id)) return null; // Google hides minor POIs at city zooms
      if (/water/.test(id)) set("text-color", p.waterLabel);
      else if (/label_(city|town|state|country)/.test(id)) set("text-color", p.labelStrong);
      else set("text-color", p.label);
      set("text-halo-color", p.halo);
      set("text-halo-width", 1.5);
      set("text-halo-blur", 0);
      if (id.startsWith("poi")) set("icon-opacity", 0.8);
      break;
    case "raster":
      return null;
  }
  return { ...layer, paint } as LayerSpecification;
}

export interface VectorBasemap {
  glyphs: string;
  sprite: string;
  sources: Record<string, SourceSpecification>;
  layers: LayerSpecification[];
}

/** Namespaced so the basemap never collides with overlay ids. */
export const OSM_PREFIX = "osm:";

export async function googleLookBasemap(theme: ResolvedTheme): Promise<VectorBasemap> {
  const style = await loadSourceStyle();
  const p = PALETTE[theme];
  const layers: LayerSpecification[] = [];
  for (const layer of style.layers) {
    if (layer.type === "background") continue; // the map's own background is recoloured instead
    if (!("source" in layer) || layer.source !== "openmaptiles") continue;
    const next = recolour(layer, p);
    if (!next) continue;
    layers.push({
      ...next,
      id: OSM_PREFIX + next.id,
      source: OSM_PREFIX + "openmaptiles",
    } as LayerSpecification);
  }
  const omt = style.sources.openmaptiles as SourceSpecification;
  return {
    glyphs: style.glyphs as string,
    sprite: style.sprite as string,
    sources: { [OSM_PREFIX + "openmaptiles"]: { ...omt, attribution: OSM_ATTRIBUTION } as SourceSpecification },
    layers,
  };
}
