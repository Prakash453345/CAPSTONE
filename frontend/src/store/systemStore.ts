import { create } from "zustand";
import type { ConnectionStatus, DataMode, SystemSummary, ViewMode } from "@/types";

/**
 * System-level state: connection, data mode, split-view mode and the headline
 * system summary. Screen-agnostic — every workspace and the shell read from here.
 * `TrafficDataBridge` drives connectionStatus / summary from the active data
 * provider (live WebSocket or the in-browser mock).
 */

/** How long since lastUpdate before the UI should flag data as stale. */
export const STALE_AFTER_MS = 10_000;

interface SystemState {
  connectionStatus: ConnectionStatus;
  dataMode: DataMode;
  /** True once the operator picks a mode themselves, so the startup backend
   *  probe knows not to overrule them. */
  dataModeChosen: boolean;
  viewMode: ViewMode;
  summary: SystemSummary;

  setConnectionStatus: (status: ConnectionStatus) => void;
  setDataMode: (mode: DataMode) => void;
  /** Upgrade to live only while the mode is still the untouched default. */
  adoptLiveIfUnchosen: () => void;
  setViewMode: (mode: ViewMode) => void;
  toggleViewMode: () => void;
  applySummary: (patch: Partial<SystemSummary>) => void;
}

const emptySummary: SystemSummary = {
  operational: false,
  vehicleCount: 0,
  congestion: 0,
  signalsOnline: 0,
  signalsTotal: 0,
  lastUpdate: null,
};

export const useSystemStore = create<SystemState>((set) => ({
  connectionStatus: "connecting",
  // Simulation first: the console must render something real on a cold open,
  // with no api-service or SUMO running. `adoptLiveIfUnchosen` upgrades it
  // when the startup probe finds a backend.
  dataMode: "simulation",
  dataModeChosen: false,
  viewMode: "single",
  summary: emptySummary,

  setConnectionStatus: (connectionStatus) => set({ connectionStatus }),
  setDataMode: (dataMode) => set({ dataMode, dataModeChosen: true }),
  adoptLiveIfUnchosen: () =>
    set((s) => (s.dataModeChosen ? s : { dataMode: "live" })),
  setViewMode: (viewMode) => set({ viewMode }),
  toggleViewMode: () =>
    set((s) => ({ viewMode: s.viewMode === "single" ? "split" : "single" })),
  applySummary: (patch) =>
    set((s) => ({ summary: { ...s.summary, ...patch } })),
}));

/** Selector: is the last accepted update older than the stale threshold? */
export function selectIsStale(state: SystemState, now = Date.now()): boolean {
  const { lastUpdate } = state.summary;
  if (!lastUpdate) return false;
  return now - new Date(lastUpdate).getTime() > STALE_AFTER_MS;
}
