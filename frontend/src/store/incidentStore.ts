import { create } from "zustand";
import type { Anomaly, Incident, Intersection } from "@/types";

/**
 * Shared selection + collections for incidents, anomalies and intersections.
 * The cross-workspace synchronisation ("Anomaly -> View Traffic -> focused
 * intersection") is built on the selection fields here. Collections are
 * populated by the data layer.
 *
 * (Phase 11: this used to also carry `emergencyUnits`/`activeEmergencyUnitId`
 * — the pre-Phase-3 emergency-vehicle shape. Nothing rendered off them once
 * the map moved to `emergencyStore.requests`; removed rather than kept
 * "just in case", per the standing don't-duplicate-mock/live-paths goal.)
 */

interface IncidentState {
  incidents: Incident[];
  anomalies: Anomaly[];
  intersections: Intersection[];

  selectedIncidentId: string | null;
  selectedAnomalyId: string | null;
  selectedIntersectionId: string | null;

  /**
   * Operator reviews not yet reflected by the stream, by incident id. The
   * provider re-sends its own copy of every incident each tick, still
   * "candidate" until the backend broadcasts the change; without this a
   * confirmation reverted on screen within a second.
   */
  reviews: Record<string, Incident>;

  /** Replace incidents from the data layer, keeping pending reviews on top. */
  setIncidents: (incidents: Incident[]) => void;
  /** Record an operator's confirm / reject result from the API. */
  applyReview: (reviewed: Incident) => void;
  /** Forget pending reviews (data source switched). */
  clearReviews: () => void;
  setAnomalies: (anomalies: Anomaly[]) => void;
  setIntersections: (intersections: Intersection[]) => void;

  selectIncident: (id: string | null) => void;
  selectAnomaly: (id: string | null) => void;
  selectIntersection: (id: string | null) => void;
}

export const useIncidentStore = create<IncidentState>((set) => ({
  incidents: [],
  anomalies: [],
  intersections: [],

  selectedIncidentId: null,
  selectedAnomalyId: null,
  selectedIntersectionId: null,

  reviews: {},

  setIncidents: (incoming) =>
    set((s) => {
      const reviews = { ...s.reviews };
      const incidents = incoming.map((i) => {
        const review = reviews[i.id];
        if (!review) return i;
        if (i.status === "candidate") return review; // stream not caught up yet
        delete reviews[i.id]; // stream now carries the outcome itself
        return i;
      });
      const seen = new Set(incoming.map((i) => i.id));
      for (const r of Object.values(reviews)) if (!seen.has(r.id)) incidents.push(r);
      return { incidents, reviews };
    }),
  applyReview: (reviewed) =>
    set((s) => ({
      reviews: { ...s.reviews, [reviewed.id]: reviewed },
      incidents: [...s.incidents.filter((i) => i.id !== reviewed.id), reviewed],
    })),
  clearReviews: () => set({ reviews: {} }),
  setAnomalies: (anomalies) => set({ anomalies }),
  setIntersections: (intersections) => set({ intersections }),

  selectIncident: (selectedIncidentId) => set({ selectedIncidentId }),
  selectAnomaly: (selectedAnomalyId) => set({ selectedAnomalyId }),
  selectIntersection: (selectedIntersectionId) => set({ selectedIntersectionId }),
}));

/** Selector helpers — keep component code free of find() noise. */
export const selectSelectedIncident = (s: IncidentState): Incident | null =>
  s.incidents.find((i) => i.id === s.selectedIncidentId) ?? null;

export const selectSelectedIntersection = (
  s: IncidentState,
): Intersection | null =>
  s.intersections.find((i) => i.id === s.selectedIntersectionId) ?? null;

export const selectSelectedAnomaly = (s: IncidentState): Anomaly | null =>
  s.anomalies.find((a) => a.id === s.selectedAnomalyId) ?? null;
