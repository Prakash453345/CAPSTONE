import { create } from "zustand";
import type { LatLng } from "@/types";

/**
 * Map view + layer state, shared so "View Traffic" (Phase 5) and Split View
 * (Phase 6) can drive the same map from any workspace. Rendering lands in
 * Phase 2; this store just holds intent.
 */

export type MapLayerId =
  | "vehicles"
  | "signals"
  | "congestion"
  | "incidents"
  | "anomalies"
  | "emergency"
  | "weather";

export const DEFAULT_MAP_LAYERS: MapLayerId[] = [
  "vehicles",
  "signals",
  "congestion",
  "incidents",
  "anomalies",
  "emergency",
  "weather",
];

/**
 * What a map click currently means. `idle` selects features; the others are
 * one-shot "pick a point / road" modes the operator flows enter from the
 * Create Anomaly / Emergency Response panels.
 */
export type MapInteractionMode =
  | "idle"
  | "create-anomaly"
  | "pick-source"
  | "pick-destination";

/** Vijayawada corridor centroid — matches the ITMS SUMO scenario. */
export const DEFAULT_CENTER: LatLng = { latitude: 16.5062, longitude: 80.6335 };
export const DEFAULT_ZOOM = 14;

export interface MapFocus {
  center: LatLng;
  zoom: number;
  /** Monotonic counter so repeat focuses on the same point still fire. */
  nonce: number;
}

interface MapState {
  center: LatLng;
  zoom: number;
  activeLayers: Set<MapLayerId>;
  selectedVehicleId: string | null;
  /** What a map click currently does. */
  interactionMode: MapInteractionMode;
  /** Last requested focus — the map component reacts to nonce changes. */
  focus: MapFocus;

  setView: (center: LatLng, zoom?: number) => void;
  focusOn: (center: LatLng, zoom?: number) => void;
  toggleLayer: (layer: MapLayerId) => void;
  setSelectedVehicle: (id: string | null) => void;
  setInteractionMode: (mode: MapInteractionMode) => void;
}

export const useMapStore = create<MapState>((set) => ({
  center: DEFAULT_CENTER,
  zoom: DEFAULT_ZOOM,
  activeLayers: new Set(DEFAULT_MAP_LAYERS),
  selectedVehicleId: null,
  interactionMode: "idle",
  focus: { center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, nonce: 0 },

  setView: (center, zoom) =>
    set((s) => ({ center, zoom: zoom ?? s.zoom })),
  focusOn: (center, zoom) =>
    set((s) => ({
      center,
      zoom: zoom ?? Math.max(s.zoom, 16),
      focus: { center, zoom: zoom ?? Math.max(s.zoom, 16), nonce: s.focus.nonce + 1 },
    })),
  toggleLayer: (layer) =>
    set((s) => {
      const next = new Set(s.activeLayers);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return { activeLayers: next };
    }),
  setSelectedVehicle: (selectedVehicleId) => set({ selectedVehicleId }),
  setInteractionMode: (interactionMode) => set({ interactionMode }),
}));
