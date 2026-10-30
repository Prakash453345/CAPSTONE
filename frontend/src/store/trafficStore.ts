import { create } from "zustand";
import type { Vehicle } from "@/types";

/**
 * High-frequency traffic state (vehicles ~1 Hz, congestion), kept separate
 * from selection/collection state so a vehicle tick doesn't wake components
 * that only care about incidents (spec §17).
 *
 * (Phase 11: this used to also carry `routes: ActiveRoute[]` — the
 * pre-Phase-3 route-polyline shape, unread by any component once the map
 * moved to rendering off `emergencyStore.requests[].route`; removed rather
 * than kept "just in case".)
 */
interface TrafficState {
  vehicles: Vehicle[];
  roadCongestion: Record<string, number>;
  lastTickAt: number | null;

  ingest: (patch: { vehicles: Vehicle[]; roadCongestion: Record<string, number> }) => void;
  reset: () => void;
}

export const useTrafficStore = create<TrafficState>((set) => ({
  vehicles: [],
  roadCongestion: {},
  lastTickAt: null,

  ingest: ({ vehicles, roadCongestion }) =>
    set({ vehicles, roadCongestion, lastTickAt: Date.now() }),
  reset: () => set({ vehicles: [], roadCongestion: {}, lastTickAt: null }),
}));
