import { create } from "zustand";

/**
 * Which floating sheet on the map is open. Like Google Maps, only one is open
 * at a time: opening the search results, the layers menu or the legend closes
 * whichever other one was showing, so they never stack on top of each other.
 */
export type MapSheet = "search" | "layers" | "legend";

/** A road the operator picked on the map or in search: its place card shows. */
export interface SelectedRoad {
  edgeId: string;
  /** Where on the road it was picked (click point snapped to the road). */
  at: [number, number];
}

interface MapChromeState {
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

export const useMapChromeStore = create<MapChromeState>((set) => ({
  sheet: null,
  selectedRoad: null,
  selectRoad: (selectedRoad) => set(selectedRoad ? { selectedRoad, sheet: null } : { selectedRoad }),
  open: (sheet) => set({ sheet }),
  close: (sheet) => set((s) => (s.sheet === sheet ? { sheet: null } : s)),
  toggle: (sheet) => set((s) => ({ sheet: s.sheet === sheet ? null : sheet })),
}));
