import { createContext, useContext } from "react";
import { createStore, useStore, type StoreApi } from "zustand";

/**
 * Which floating sheet on a map is open. Like Google Maps, only one is open
 * at a time: opening the search results, the layers menu, the legend or the
 * weather panel closes whichever other one was showing.
 *
 * Scoped per map: each TrafficMap creates its own store and provides it via
 * context, so split view's two maps don't open each other's sheets or cards.
 */
export type MapSheet = "search" | "layers" | "legend" | "weather";

/** A road the operator picked on the map or in search: its place card shows. */
export interface SelectedRoad {
  edgeId: string;
  /** Where on the road it was picked (click point snapped to the road). */
  at: [number, number];
}

export interface MapChromeState {
  sheet: MapSheet | null;
  selectedRoad: SelectedRoad | null;
  /** Selecting a road closes any open sheet, like opening a place in Maps. */
  selectRoad: (road: SelectedRoad | null) => void;
  open: (sheet: MapSheet) => void;
  /** Closes `sheet` only if it is the one showing, so a stale close from one
   *  sheet can't dismiss another that has since opened. */
  close: (sheet: MapSheet) => void;
  toggle: (sheet: MapSheet) => void;
}

export function createMapChromeStore(): StoreApi<MapChromeState> {
  return createStore<MapChromeState>((set) => ({
    sheet: null,
    selectedRoad: null,
    selectRoad: (selectedRoad) =>
      set(selectedRoad ? { selectedRoad, sheet: null } : { selectedRoad }),
    open: (sheet) => set({ sheet }),
    close: (sheet) => set((s) => (s.sheet === sheet ? { sheet: null } : s)),
    toggle: (sheet) => set((s) => ({ sheet: s.sheet === sheet ? null : sheet })),
  }));
}

export const MapChromeContext = createContext<StoreApi<MapChromeState> | null>(null);

/** Read this map's chrome state; must render inside a TrafficMap. */
export function useMapChromeStore<T>(selector: (s: MapChromeState) => T): T {
  const store = useContext(MapChromeContext);
  if (!store) throw new Error("useMapChromeStore must be used inside <TrafficMap>");
  return useStore(store, selector);
}
