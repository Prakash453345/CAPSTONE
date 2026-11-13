import type { EmergencyRequest } from "@/types";

/** The note sim-service puts on a request a crew asked a corridor for. */
export const CORRIDOR_ASK_PREFIX = "Crew asked for a green corridor";

/** A crew's own request for a corridor, still waiting for an operator. */
export function isCorridorAsk(r: Pick<EmergencyRequest, "state" | "detail">): boolean {
  return r.state === "route_ready" && Boolean(r.detail?.startsWith(CORRIDOR_ASK_PREFIX));
}

/** Only police and traffic police crews may ask; ambulances and fire trucks get a corridor from dispatch. */
export function canAskCorridor(kind: string | undefined): boolean {
  return kind === "police" || kind === "traffic_police";
}
