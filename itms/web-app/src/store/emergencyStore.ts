import { useMemo } from "react";
import { create } from "zustand";
import type {
  CorridorReservationView,
  EmergencyRequest,
  EmergencyRouteView,
  EmergencyVehicleKind,
  GreenCorridorView,
  LatLng,
} from "@/types";

/**
 * Emergency-response workspace state: the live requests (from the data layer),
 * the operator's in-progress dispatch draft, and which request is selected.
 * Kept separate from `incidentStore` so a route-progress tick doesn't wake
 * incident/anomaly views.
 */

export interface PresetUnit {
  id: string;
  callSign: string;
  kind: EmergencyVehicleKind;
}

/** A couple of always-available simulated responders for the prototype. */
export const PRESET_UNITS: PresetUnit[] = [
  { id: "EV-001", callSign: "Ambulance 12", kind: "ambulance" },
  { id: "EV-002", callSign: "Ambulance 27", kind: "ambulance" },
  { id: "EV-101", callSign: "Fire 4", kind: "fire_truck" },
  { id: "EV-201", callSign: "Police 9", kind: "police" },
];

/** One end of the dispatch being drafted — a map click resolved to an edge. */
export interface RoutePoint {
  edgeId: string;
  edgeName: string | null;
  at: [number, number]; // [lng, lat]
}

export interface DispatchDraft {
  unit: PresetUnit;
  source: RoutePoint | null;
  destination: RoutePoint | null;
}

interface EmergencyState {
  requests: EmergencyRequest[];
  selectedRequestId: string | null;
  draft: DispatchDraft | null;
  /** Which route of the selected request the operator is inspecting:
   *  0 = recommended, 1.. = an alternative. Reset to 0 on selection change.
   *  Preview only — the recommended route is always what the backend dispatches. */
  previewRank: number;
  /** Terminal requests the operator has explicitly dismissed from the roster
   *  (Phase 6). The data layer keeps emitting them for a while after they
   *  complete/cancel (see `wsProvider`'s long safety-net prune) — this is the
   *  real, operator-driven removal from view. */
  archivedRequestIds: Set<string>;

  setRequests: (requests: EmergencyRequest[]) => void;
  selectRequest: (id: string | null) => void;
  setPreviewRank: (rank: number) => void;
  archiveRequest: (id: string) => void;

  startDraft: (unit: PresetUnit) => void;
  setDraftUnit: (unit: PresetUnit) => void;
  setDraftPoint: (which: "source" | "destination", point: RoutePoint) => void;
  clearDraft: () => void;
}

export const useEmergencyStore = create<EmergencyState>((set) => ({
  requests: [],
  selectedRequestId: null,
  draft: null,
  previewRank: 0,
  archivedRequestIds: new Set(),

  setRequests: (requests) => set({ requests }),
  selectRequest: (selectedRequestId) => set({ selectedRequestId, previewRank: 0 }),
  setPreviewRank: (previewRank) => set({ previewRank }),
  archiveRequest: (id) =>
    set((s) => ({ archivedRequestIds: new Set(s.archivedRequestIds).add(id) })),

  startDraft: (unit) => set({ draft: { unit, source: null, destination: null } }),
  setDraftUnit: (unit) =>
    set((s) => ({ draft: s.draft ? { ...s.draft, unit } : { unit, source: null, destination: null } })),
  setDraftPoint: (which, point) =>
    set((s) => (s.draft ? { draft: { ...s.draft, [which]: point } } : {})),
  clearDraft: () => set({ draft: null }),
}));

export const selectSelectedRequest = (s: EmergencyState): EmergencyRequest | null =>
  s.requests.find((r) => r.id === s.selectedRequestId) ?? null;

/** A request with no more state changes coming — arrived/completed or stood down. */
export function isTerminalRequest(req: Pick<EmergencyRequest, "state">): boolean {
  return req.state === "completed" || req.state === "cancelled";
}

/** Every request still in progress, in store order. The map (and any "N active
 *  missions" readout) renders this set, not just the selected one.
 *
 *  Pure — safe to call as a plain function (tests, or composed inside another
 *  selector like `DashboardPage`'s `.length` read). Do NOT pass this straight
 *  to `useEmergencyStore(...)` as a component's selector: it allocates a new
 *  array every call, so `useSyncExternalStore`'s snapshot never stabilises
 *  and React throws "Maximum update depth exceeded" ("the result of
 *  getSnapshot should be cached"). Use `useActiveRequests()` below instead. */
export const selectActiveRequests = (s: EmergencyState): EmergencyRequest[] =>
  s.requests.filter((r) => !isTerminalRequest(r));

/** Every request the roster should still list — everything except what the
 *  operator has explicitly archived (Phase 6). Unlike `selectActiveRequests`,
 *  this keeps terminal requests around so their mission summary stays visible
 *  until dismissed.
 *
 *  Same caveat as `selectActiveRequests`: pure and test-safe, but never pass
 *  this directly to `useEmergencyStore(...)` in a component — use
 *  `useVisibleRequests()` below. */
export const selectVisibleRequests = (s: EmergencyState): EmergencyRequest[] =>
  s.requests.filter((r) => !s.archivedRequestIds.has(r.id));

/** Memoized, component-safe version of `selectActiveRequests`: subscribes to
 *  the raw `requests` array (stable until the store really replaces it) and
 *  only re-filters when that reference actually changes, instead of
 *  allocating a new array on every render/snapshot check. */
export function useActiveRequests(): EmergencyRequest[] {
  const requests = useEmergencyStore((s) => s.requests);
  return useMemo(() => requests.filter((r) => !isTerminalRequest(r)), [requests]);
}

/** Memoized, component-safe version of `selectVisibleRequests` — see
 *  `useActiveRequests` for why this indirection matters. */
export function useVisibleRequests(): EmergencyRequest[] {
  const requests = useEmergencyStore((s) => s.requests);
  const archivedRequestIds = useEmergencyStore((s) => s.archivedRequestIds);
  return useMemo(
    () => requests.filter((r) => !archivedRequestIds.has(r.id)),
    [requests, archivedRequestIds],
  );
}

/**
 * How many times a request was rerouted (operator recalculation or an
 * automatic one), derived from its client-side timeline. A REROUTE action
 * never changes `state` in the backend's state machine (`route_ready` stays
 * `route_ready`, `in_transit` stays `in_transit`) — every other action does —
 * so a timeline entry whose state matches the one immediately before it is
 * exactly a reroute; nothing else produces that shape.
 */
export function rerouteCount(req: Pick<EmergencyRequest, "timeline">): number {
  let n = 0;
  for (let i = 1; i < req.timeline.length; i++) {
    if (req.timeline[i].state === req.timeline[i - 1].state) n++;
  }
  return n;
}

/** Every route the selected request offers, recommended first. */
export function requestRoutes(req: EmergencyRequest | null): EmergencyRouteView[] {
  if (!req?.route) return [];
  return [req.route, ...req.alternatives];
}

/** The route currently being inspected (falls back to the recommended one). */
export const selectPreviewedRoute = (s: EmergencyState): EmergencyRouteView | null => {
  const routes = requestRoutes(selectSelectedRequest(s));
  return routes[s.previewRank] ?? routes[0] ?? null;
};

/** Straight-line preview point for a draft end (until a real route exists). */
export function draftLatLng(p: RoutePoint | null): LatLng | null {
  return p ? { longitude: p.at[0], latitude: p.at[1] } : null;
}

/** The corridor's reservations in route order, regardless of what order
 *  they arrived on the wire in. */
export function orderedReservations(
  corridor: GreenCorridorView,
): CorridorReservationView[] {
  return [...corridor.reservations].sort((a, b) => a.order - b.order);
}

/** The next junction the corridor still needs to clear — the first
 *  reservation, in route order, not yet in `passedIntersections`. `null` once
 *  every junction has been passed (the corridor is about to / has completed). */
export function nextCorridorReservation(
  corridor: GreenCorridorView,
): CorridorReservationView | null {
  const passed = new Set(corridor.passedIntersections);
  return orderedReservations(corridor).find((r) => !passed.has(r.intersectionId)) ?? null;
}

/** How long a reservation holds its junction, in seconds — a duration
 *  (`close - open`), not "time until it opens": the timestamps are sim-clock,
 *  not the browser's, so only a duration stays meaningful client-side. */
export function corridorHoldSeconds(
  r: Pick<CorridorReservationView, "openAtMs" | "closeAtMs">,
): number {
  return Math.max(0, Math.round((r.closeAtMs - r.openAtMs) / 1000));
}
