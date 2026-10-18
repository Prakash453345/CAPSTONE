import { useEffect } from "react";
import { useChangeGuard } from "@/components/map/useChangeGuard";
import type { GeoJSONSource } from "maplibre-gl";
import type { FeatureCollection, LineString } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useTrafficStore } from "@/store/trafficStore";
import { useThemeStore } from "@/store/themeStore";
import { CONGESTION_STOPS } from "@/components/map/mapColors";
import { roadEdges } from "@/data/network";

const SRC = "roads";
const CASING = "roads-casing";
const LINE = "roads-line";

function buildData(
  congestion: Record<string, number>,
): FeatureCollection<LineString, { edgeId: string; congestion: number }> {
  return {
    type: "FeatureCollection",
    features: roadEdges.map((e) => ({
      type: "Feature",
      properties: { edgeId: e.id, congestion: congestion[e.id] ?? 0 },
      geometry: { type: "LineString", coordinates: e.path },
    })),
  };
}

/** Road centrelines. `visible` colours them by live congestion; otherwise flat. */
export function RoadLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const congestion = useTrafficStore((s) => s.roadCongestion);
  const changed = useChangeGuard();

  useEffect(() => {
    if (!map.getSource(SRC)) {
      map.addSource(SRC, { type: "geojson", data: buildData({}) });
      map.addLayer({
        id: CASING,
        type: "line",
        source: SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": useThemeStore.getState().resolved === "dark" ? "#1f2124" : "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 3, 17, 12],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: LINE,
        type: "line",
        source: SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.4, 14, 2.4, 17, 7],
          // Free-flowing roads recede; congestion is what should catch the eye.
          "line-opacity": ["interpolate", ["linear"], ["get", "congestion"], 0, 0.5, 0.35, 0.9, 0.6, 1],
        },
      });
    }
    return () => {
      for (const id of [LINE, CASING]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map]);

  useEffect(() => {
    const src = map.getSource(SRC) as GeoJSONSource | undefined;
    if (!src) return;
    // Two decimals is finer than the colour ramp can show.
    if (!changed(roadEdges.map((e) => (congestion[e.id] ?? 0).toFixed(2)).join(","))) return;
    src.setData(buildData(congestion));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `changed` is stable per mount
  }, [map, congestion]);

  useEffect(() => {
    if (!map.getLayer(LINE)) return;
    map.setPaintProperty(
      LINE,
      "line-color",
      visible
        ? [
            "interpolate",
            ["linear"],
            ["get", "congestion"],
            ...CONGESTION_STOPS.flat(),
          ]
        : "#9aa0a6",
    );
  }, [map, visible]);

  // Google draws traffic lines on a casing the colour of the map itself.
  const theme = useThemeStore((s) => s.resolved);
  useEffect(() => {
    if (!map.getLayer(CASING)) return;
    map.setPaintProperty(CASING, "line-color", theme === "dark" ? "#1f2124" : "#ffffff");
  }, [map, theme]);

  return null;
}
