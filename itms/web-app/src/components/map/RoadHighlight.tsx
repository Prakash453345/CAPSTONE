import { useEffect } from "react";
import type { GeoJSONSource } from "maplibre-gl";
import { useMapInstance } from "@/components/map/MapContext";
import { HIGHLIGHT_BLUE } from "@/components/map/mapChrome";
import { edgeById } from "@/data/network";
import { useMapChromeStore } from "@/store/mapChromeStore";

const SRC = "road-highlight";
const BAND = "road-highlight-band";
/** RoadLayer's congestion line; the band goes directly beneath it. */
const ROAD_LINE = "roads-line";

/**
 * Outlines the selected road in Google blue, the way Maps marks a searched or
 * tapped street, without hiding its live congestion colour.
 */
export function RoadHighlight() {
  const map = useMapInstance();
  const selected = useMapChromeStore((s) => s.selectedRoad);

  useEffect(() => {
    if (!map.getSource(SRC)) {
      map.addSource(SRC, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      // A blue band wider than the traffic line, slotted between the road
      // casing and the congestion line: the road keeps its traffic colour and
      // gains a Google-blue outline (RoadLayer mounts first, so it exists).
      map.addLayer(
        {
          id: BAND,
          type: "line",
          source: SRC,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": HIGHLIGHT_BLUE,
            "line-width": ["interpolate", ["linear"], ["zoom"], 12, 8, 17, 22],
            "line-opacity": 0.9,
          },
        },
        map.getLayer(ROAD_LINE) ? ROAD_LINE : undefined,
      );
    }
    return () => {
      if (map.getLayer(BAND)) map.removeLayer(BAND);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map]);

  useEffect(() => {
    const edge = selected ? edgeById.get(selected.edgeId) : undefined;
    (map.getSource(SRC) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: edge
        ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: edge.path } }]
        : [],
    });
  }, [map, selected]);

  return null;
}
