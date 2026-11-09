import { useMemo, useRef } from "react";
import { isTerminalRequest, requestRoutes, useEmergencyStore } from "@/store/emergencyStore";
import { useCrewStore } from "@/store/crewStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useTrafficStore } from "@/store/trafficStore";
import { unitName } from "@/components/console/words";
import { pointAlongPath, type LngLat } from "@/utils/geo";
import type { EmergencyRequest, EmergencyRouteView, EmergencyVehicleKind, GreenCorridorView } from "@/types";
import { buildPlan, maneuverAfter, nextManeuver, type Maneuver, type RoutePlan } from "@/crew/plan";
import {
  alongFor,
  hasArrived,
  hazardsAhead,
  remainingSeconds,
  upcomingSignals,
  type Hazard,
  type UpcomingSignal,
} from "@/crew/situation";

export interface UnitOption {
  id: string;
  name: string;
  /** Ambulance, police or fire truck, when a call has told us. */
  kind?: EmergencyVehicleKind;
  /** Has a mission that is still on the road. */
  active: boolean;
}

/** One route the system offers for a call, with its drawable plan. */
export interface RouteChoice {
  view: EmergencyRouteView;
  plan: RoutePlan | null;
}

export interface Mission {
  request: EmergencyRequest;
  plan: RoutePlan | null;
  /** The recommended route first, then any alternatives (preview only: dispatch uses the first). */
  routes: RouteChoice[];
  corridor: GreenCorridorView | undefined;
  /** Where the vehicle is, [lng, lat], and which way it points. */
  position: LngLat | null;
  headingDeg: number | null;
  alongM: number;
  offRouteM: number;
  remainingM: number;
  /** Seconds to go, when the system can say. */
  etaS: number | null;
  arrived: boolean;
  /** The vehicle is moving under dispatch, so guidance (not the briefing) applies. */
  underway: boolean;
  next: Maneuver | null;
  nextDistM: number;
  then: Maneuver | null;
  signals: UpcomingSignal[];
  hazards: Hazard[];
}

/** Everyone a responder might be: the fleet (crew accounts) plus any unit with a request.
 *  Units are whoever dispatch has sent (the nearest free crew of the right
 *  kind), so there is no fixed list beyond the fleet itself. */
export function unitOptions(
  requests: readonly EmergencyRequest[],
  fleet: readonly { unitId: string; callSign: string }[] = [],
): UnitOption[] {
  const byId = new Map<string, UnitOption>();
  for (const u of fleet) byId.set(u.unitId, { id: u.unitId, name: u.callSign || unitName(u.unitId), active: false });
  for (const r of requests) {
    const known = byId.get(r.vehicleId);
    const active = !isTerminalRequest(r);
    byId.set(r.vehicleId, {
      id: r.vehicleId,
      name: unitName(r.vehicleId),
      kind: r.vehicleKind,
      active: active || !!known?.active,
    });
  }
  return [...byId.values()].sort((a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name));
}

/** The request a unit should be following: its live one, else its latest finished one. */
export function requestForUnit(requests: readonly EmergencyRequest[], unitId: string | null): EmergencyRequest | null {
  if (!unitId) return null;
  const mine = requests.filter((r) => r.vehicleId === unitId);
  return (
    mine.find((r) => !isTerminalRequest(r)) ??
    [...mine].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0] ??
    null
  );
}

/**
 * Everything the crew page shows about one unit's mission, derived from the
 * app's live stores. Recomputed whenever a snapshot lands (about once a
 * second); all the real logic lives in the pure functions under `src/crew`.
 */
export function useMission(unitId: string | null): { request: EmergencyRequest | null; mission: Mission | null; units: UnitOption[] } {
  const requests = useEmergencyStore((s) => s.requests);
  const intersections = useIncidentStore((s) => s.intersections);
  const anomalies = useIncidentStore((s) => s.anomalies);
  const congestion = useTrafficStore((s) => s.roadCongestion);
  const lastAlong = useRef(0);

  const fleet = useCrewStore((s) => s.fleet);
  const units = useMemo(() => unitOptions(requests, fleet), [requests, fleet]);
  const request = useMemo(() => requestForUnit(requests, unitId), [requests, unitId]);

  const edgesKey = request?.route?.edges.join(",") ?? "";
  const corridor = request?.corridor;
  const signalIds = useMemo(() => {
    const ids = new Set(request?.route?.signalisedIntersections ?? []);
    for (const r of corridor?.reservations ?? []) ids.add(r.intersectionId);
    return [...ids];
  }, [request?.route?.signalisedIntersections, corridor?.reservations]);
  // Rebuilt only when the route itself changes, not on every position tick.
  const plan = useMemo(
    () => (edgesKey ? buildPlan(edgesKey.split(","), signalIds) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- edgesKey/signalIds stand for the route
    [edgesKey, signalIds.join(",")],
  );

  const altKey = request?.alternatives.map((a) => a.edges.join(",")).join("|") ?? "";
  const routes = useMemo<RouteChoice[]>(
    () =>
      requestRoutes(request).map((view, i) => ({
        view,
        plan: i === 0 ? plan : buildPlan(view.edges, view.signalisedIntersections),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the recommended route and its alternatives stand for the edges
    [plan, altKey, request?.route?.etaS],
  );

  const mission = useMemo<Mission | null>(() => {
    if (!request) return null;
    const live = request.live;
    const base = {
      request,
      plan,
      routes,
      corridor,
      position: live?.lat != null && live?.lon != null ? ([live.lon, live.lat] as LngLat) : null,
    };
    if (!plan) {
      return {
        ...base,
        headingDeg: null,
        alongM: 0,
        offRouteM: 0,
        remainingM: request.route?.totalDistanceM ?? 0,
        etaS: remainingSeconds(request, request.route?.totalDistanceM ?? 0),
        arrived: request.state === "completed",
        underway: false,
        next: null,
        nextDistM: 0,
        then: null,
        signals: [],
        hazards: [],
      };
    }
    const { alongM, offRouteM } = alongFor(plan, live, lastAlong.current);
    lastAlong.current = alongM;
    const remainingM = Math.max(0, plan.totalM - alongM);
    const next = nextManeuver(plan, alongM);
    const underway =
      request.state === "in_transit" || request.state === "green_corridor_active" || live?.status === "en_route";
    return {
      ...base,
      headingDeg: pointAlongPath(plan.coords, plan.cum, alongM).headingDeg,
      alongM,
      offRouteM,
      remainingM,
      etaS: remainingSeconds(request, remainingM),
      arrived: hasArrived(request, remainingM),
      underway: underway && !isTerminalRequest(request),
      next,
      nextDistM: Math.max(0, next.atM - alongM),
      then: maneuverAfter(plan, next),
      signals: upcomingSignals(plan, alongM, { intersections, corridor, limit: 4 }),
      hazards: hazardsAhead(plan, alongM, {
        anomalies,
        congestion,
        intersections,
        requests,
        ownRequestId: request.id,
        unitNames: unitName,
      }),
    };
  }, [request, plan, routes, corridor, intersections, anomalies, congestion, requests]);

  return { request, mission, units };
}
