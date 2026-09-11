import type { StyleSpecification } from "maplibre-gl";

/**
 * Dark, key-free basemap: OpenStreetMap raster tiles, dimmed and desaturated so
 * they sit quietly behind the operational overlays. Same tile source the existing
 * ITMS live page uses. No `glyphs` — every overlay uses circle / line / icon
 * layers, so nothing depends on a remote font endpoint.
 */
export const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#0a0e14" },
    },
    {
      id: "basemap",
      type: "raster",
      source: "basemap",
      paint: {
        "raster-opacity": 0.55,
        "raster-saturation": -0.7,
        "raster-contrast": -0.08,
        "raster-brightness-max": 0.85,
      },
    },
  ],
};
