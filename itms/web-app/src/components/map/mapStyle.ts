import type { StyleSpecification } from "maplibre-gl";

/**
 * CARTO's dark raster basemap, with OSM/CARTO attribution. Operational overlays
 * use the bundled SUMO geometry independently of tile availability. No glyphs
 * endpoint is needed for circle / line / icon layers. Public deployments must
 * review the tile provider's usage terms and capacity requirements.
 */
export const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [
        "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
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
        "raster-opacity": 0.95,
        "raster-saturation": -0.15,
        "raster-contrast": 0.05,
      },
    },
  ],
};
