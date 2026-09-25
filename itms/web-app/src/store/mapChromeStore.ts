import { create } from "zustand";

/**
 * Which floating sheet on the map is open. Like Google Maps, only one is open
 * at a time: opening the search results, the layers menu or the legend closes
 * whichever other one was showing, so they never stack on top of each other.
 */
export type MapSheet = "search" | "layers" | "legend";

interface MapChromeState {
  sheet: MapSheet | null;
  open: (sheet: MapSheet) => void;
  /** Closes `sheet` only if it is the one showing, so a stale close from one
   *  sheet can't dismiss another that has since opened. */
  close: (sheet: MapSheet) => void;
  toggle: (sheet: MapSheet) => void;
}

export const useMapChromeStore = create<MapChromeState>((set) => ({
  sheet: null,
  open: (sheet) => set({ sheet }),
  close: (sheet) => set((s) => (s.sheet === sheet ? { sheet: null } : s)),
  toggle: (sheet) => set((s) => ({ sheet: s.sheet === sheet ? null : sheet })),
}));
