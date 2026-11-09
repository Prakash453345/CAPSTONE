import type {
  ExpressionSpecification,
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import type { ResolvedTheme } from "@/store/themeStore";
import { POI_ICON, poiTextColor } from "@/components/map/poiBadges";
import { OSM_PREFIX } from "@/components/map/mapStyle";

/**
 * Keyless basemap: OpenFreeMap's OpenMapTiles vector data (free, no key, no
 * request limits), redrawn in Apple Maps' manner: slate-blue land and royal
 * water at night, warm paper by day, district and road names in tracked
 * capitals, and points of interest as coloured category badges.
 */
const SOURCE_STYLE = "https://tiles.openfreemap.org/styles/liberty";
export const OSM_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener noreferrer">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>';

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
  /** Road names. */
  label: string;
  /** Neighbourhood and district names, set in tracked capitals. */
  district: string;
  /** Town and city names. */
  labelStrong: string;
  halo: string;
}

// Dark is sampled from Apple Maps' dark rendering (land #34455b, roads
// #6d7e94, water #1e347a, parkland #0c6663, district names #d0e1f5); light
// follows Apple's daytime map.
const PALETTE: Record<ResolvedTheme, Palette> = {
  light: {
    land: "#f4f2ed",
    landAlt: "#eeebe4",
    park: "#c5e6b5",
    water: "#97cdf6",
    waterLabel: "#2f6ea6",
    building: "#e7e3dc",
    buildingLine: "#dbd5cb",
    road: "#ffffff",
    roadCasing: "#dcd6cc",
    arterial: "#ffffff",
    arterialCasing: "#d1cabe",
    highway: "#fcd57a",
    highwayCasing: "#e3ac4c",
    rail: "#cdc7bd",
    boundary: "#a39e95",
    label: "#5b5955",
    district: "#827d75",
    labelStrong: "#36342f",
    halo: "#ffffff",
  },
  dark: {
    land: "#33445a",
    landAlt: "#364860",
    park: "#10625e",
    water: "#1e347a",
    waterLabel: "#8ea8e8",
    building: "#3a4c62",
    buildingLine: "#42556d",
    road: "#61728a",
    roadCasing: "#2c3b4f",
    arterial: "#6d7e95",
    arterialCasing: "#2c3b4f",
    highway: "#8798b0",
    highwayCasing: "#2c3b4f",
    rail: "#4b5c73",
    boundary: "#6d7e94",
    label: "#c4d2e4",
    district: "#d0e1f5",
    labelStrong: "#f2f6fc",
    halo: "#2c3a4c",
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

/** English name only: Apple shows one script, not a second line of Telugu. */
const NAME: ExpressionSpecification = ["coalesce", ["get", "name_en"], ["get", "name:latin"], ["get", "name"]];

/** Apple's label voice: bold, quiet, and in tracked capitals for districts and roads. */
function relabel(id: string, layout: Record<string, unknown>, paint: Record<string, unknown>, p: Palette, theme: ResolvedTheme) {
  if ("text-field" in layout) layout["text-field"] = NAME;
  paint["text-halo-color"] = p.halo;
  paint["text-halo-width"] = theme === "dark" ? 1.2 : 1.5;
  paint["text-halo-blur"] = 0;

  if (/^water/.test(id)) {
    paint["text-color"] = p.waterLabel;
  } else if (id.startsWith("highway-name")) {
    layout["text-font"] = ["Noto Sans Bold"];
    layout["text-transform"] = "uppercase";
    layout["text-letter-spacing"] = 0.1;
    layout["text-size"] = ["interpolate", ["linear"], ["zoom"], 13, 9.5, 16, 11.5, 19, 13];
    paint["text-color"] = p.label;
  } else if (id === "label_other" || id === "label_village") {
    layout["text-font"] = ["Noto Sans Bold"];
    layout["text-transform"] = "uppercase";
    layout["text-letter-spacing"] = 0.12;
    layout["text-size"] = ["interpolate", ["linear"], ["zoom"], 11, 10, 15, 13];
    layout["text-max-width"] = 7;
    delete layout["icon-image"];
    paint["text-color"] = p.district;
  } else if (/^label_(town|city)/.test(id)) {
    layout["text-font"] = ["Noto Sans Bold"];
    delete layout["icon-image"];
    layout["text-anchor"] = "center";
    paint["text-color"] = p.labelStrong;
  } else if (id.startsWith("label")) {
    layout["text-font"] = ["Noto Sans Bold"];
    paint["text-color"] = p.labelStrong;
  } else {
    paint["text-color"] = p.label;
  }
}

/** Points of interest as Apple-style badges: a coloured disc, label beside it in the same hue. */
function asBadge(layout: Record<string, unknown>, paint: Record<string, unknown>, theme: ResolvedTheme) {
  layout["icon-image"] = POI_ICON;
  layout["icon-size"] = 1;
  layout["icon-padding"] = 2;
  layout["text-font"] = ["Noto Sans Bold"];
  layout["text-size"] = 11.5;
  layout["text-anchor"] = "left";
  layout["text-justify"] = "left";
  layout["text-offset"] = [1.05, 0];
  layout["text-max-width"] = 8;
  // Badge and name stand or fall together, so collisions thin the map
  // instead of leaving a field of unlabelled discs.
  layout["text-optional"] = false;
  layout["symbol-sort-key"] = ["get", "rank"];
  paint["text-color"] = poiTextColor(theme);
  paint["icon-opacity"] = 1;
}

/** One layer's paint and labels, re-expressed in the Apple palette. */
function restyle(layer: LayerSpecification, p: Palette, theme: ResolvedTheme): LayerSpecification | null {
  const id = layer.id;
  // Shaded relief, hatching, one-way arrows and shields have no Apple equivalent here.
  if (id === "natural_earth" || id === "road_area_pattern" || id.endsWith("_hatching")) return null;
  if (id.startsWith("highway-shield") || id === "road_shield_us" || /one_way/.test(id)) return null;

  const paint = { ...(layer.paint ?? {}) } as Record<string, unknown>;
  const layout = { ...(layer.layout ?? {}) } as Record<string, unknown>;
  const set = (k: string, v: unknown) => (paint[k] = v);
  let minzoom = layer.minzoom;

  switch (layer.type) {
    case "background":
      set("background-color", p.land);
      break;
    case "fill":
      if (/outline/.test(id)) return null;
      if (/park|wood|grass|pitch|cemetery/.test(id)) set("fill-color", p.park);
      else if (/water/.test(id)) set("fill-color", p.water);
      else if (id === "building") {
        set("fill-color", p.building);
        set("fill-outline-color", p.buildingLine);
      } else if (/residential/.test(id)) set("fill-color", p.land);
      else set("fill-color", p.landAlt);
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
        set("line-color", isMajor(id) ? p.highwayCasing : isArterial(id) ? p.arterialCasing : p.roadCasing);
      } else if (/aeroway/.test(id)) set("line-color", p.road);
      else if (/path|pedestrian/.test(id)) set("line-color", p.roadCasing);
      else set("line-color", isMajor(id) ? p.highway : isArterial(id) ? p.arterial : p.road);
      break;
    case "symbol":
      if (/^poi_r(7|20)$/.test(id)) return null; // minor pins stay hidden at city zooms
      if (id === "poi_r1" || id === "poi_transit") {
        asBadge(layout, paint, theme);
        // Apple shows landmarks a step earlier than OpenFreeMap's default.
        minzoom = id === "poi_r1" ? 13.5 : 15;
        paint["text-halo-color"] = p.halo;
        paint["text-halo-width"] = theme === "dark" ? 1.2 : 1.5;
        paint["text-halo-blur"] = 0;
        layout["text-field"] = NAME;
      } else {
        relabel(id, layout, paint, p, theme);
      }
      break;
    case "raster":
      return null;
  }
  // Bus stops would pin every block; Apple keeps transit to stations.
  const filter =
    id === "poi_transit"
      ? (["match", ["get", "class"], ["airport", "rail"], true, false] as ExpressionSpecification)
      : id === "poi_r1" && "filter" in layer
        ? (["all", layer.filter, ["!=", ["get", "class"], "bus"]] as ExpressionSpecification)
        : undefined;
  return {
    ...layer,
    layout,
    paint,
    ...(minzoom !== undefined ? { minzoom } : {}),
    ...(filter ? { filter } : {}),
  } as LayerSpecification;
}

export interface VectorBasemap {
  glyphs: string;
  sprite: string;
  sources: Record<string, SourceSpecification>;
  layers: LayerSpecification[];
}

export async function appleLookBasemap(theme: ResolvedTheme): Promise<VectorBasemap> {
  const style = await loadSourceStyle();
  const p = PALETTE[theme];
  const layers: LayerSpecification[] = [];
  for (const layer of style.layers) {
    if (layer.type === "background") continue; // the map's own background is recoloured instead
    if (!("source" in layer) || layer.source !== "openmaptiles") continue;
    const next = restyle(layer, p, theme);
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
