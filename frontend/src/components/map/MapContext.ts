import { createContext, useContext } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

/** Shares the live MapLibre instance with layer components. Null until ready. */
export const MapContext = createContext<MapLibreMap | null>(null);

export function useMapInstance(): MapLibreMap {
  const map = useContext(MapContext);
  if (!map) {
    throw new Error("Map layer components must render inside <TrafficMap>");
  }
  return map;
}
