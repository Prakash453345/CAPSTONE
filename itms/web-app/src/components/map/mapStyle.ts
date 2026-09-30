import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { ResolvedTheme } from "@/store/themeStore";
import type { VectorBasemap } from "@/components/map/googleLookStyle";

/** Land colour under the tiles, matched to each basemap so pans never flash. */
export const BACKGROUND: Record<ResolvedTheme, string> = {
  light: "#f5f5f5",
  dark: "#1f2124",
};

/**
 * The map starts with only a background; the basemap is inserted by
 * `setBasemap` once its provider is known (Google tiles need an async session
 * token, the keyless style an async fetch). Operational overlays use the
 * bundled SUMO geometry independently of tile availability.
 */
export function initialStyle(theme: ResolvedTheme): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": BACKGROUND[theme] },
      },
    ],
  };
}

export type BasemapSpec =
  | { provider: "google"; tiles: string[] }
  | { provider: "osm"; style: VectorBasemap };

/** Ids this module installed on each map, so a swap removes exactly those. */
const installed = new WeakMap<MapLibreMap, { layers: string[]; sources: string[] }>();

function removeBasemap(map: MapLibreMap) {
  const prev = installed.get(map);
  if (!prev) return;
  for (const id of prev.layers) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of prev.sources) if (map.getSource(id)) map.removeSource(id);
  installed.delete(map);
}

/**
 * Swap the basemap in place, underneath every overlay. Using setStyle instead
 * would drop the overlay sources, layers and icons the layer components own.
 */
export function setBasemap(map: MapLibreMap, theme: ResolvedTheme, spec: BasemapSpec) {
  map.setPaintProperty("background", "background-color", BACKGROUND[theme]);
  removeBasemap(map);

  // Directly above the background, i.e. below the first overlay layer.
  const order = map.getStyle().layers ?? [];
  const beforeId = order[order.findIndex((l) => l.id === "background") + 1]?.id;

  if (spec.provider === "google") {
    map.addSource("basemap", {
      type: "raster",
      tiles: spec.tiles,
      tileSize: 256,
      maxzoom: 22,
    });
    map.addLayer(
      { id: "basemap", type: "raster", source: "basemap", paint: { "raster-fade-duration": 200 } },
      beforeId,
    );
    installed.set(map, { layers: ["basemap"], sources: ["basemap"] });
    return;
  }

  const { style } = spec;
  map.setGlyphs(style.glyphs);
  if (!map.getStyle().sprite) map.setSprite(style.sprite);
  for (const [id, src] of Object.entries(style.sources)) map.addSource(id, src);
  for (const layer of style.layers) map.addLayer(layer, beforeId);
  installed.set(map, {
    layers: style.layers.map((l) => l.id),
    sources: Object.keys(style.sources),
  });
}
