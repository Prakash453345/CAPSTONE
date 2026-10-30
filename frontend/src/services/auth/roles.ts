import type { EmergencyVehicleKind } from "@/types";

/**
 * What an account is for. The server decides (the `role` on the account) and
 * reports it with the session; the pages only follow it, so nobody picks a
 * "login type" and a crew member cannot sign in as an operator by choosing it.
 *
 *  - operator:  runs the console; may also open the crew page (to see what a crew sees)
 *  - responder: follows a dispatched route on the crew page; cannot open the console
 */
export type Role = "operator" | "responder";

export const parseRole = (raw: unknown): Role => (raw === "responder" ? "responder" : "operator");

const UNIT_KINDS: readonly EmergencyVehicleKind[] = ["ambulance", "police", "fire_truck"];

/** What a crew account drives, as the server reports it; null when it says nothing usable. */
export const parseUnitKind = (raw: unknown): EmergencyVehicleKind | null =>
  UNIT_KINDS.find((k) => k === raw) ?? null;

/** Where an account lands after signing in. */
export const homeFor = (role: Role): string => (role === "responder" ? "/crew" : "/console");

const inArea = (path: string, area: string) => path === area || path.startsWith(`${area}/`);

/** Whether this role may open `path` (a pathname, possibly with a query or hash). */
export function canOpen(role: Role, path: string): boolean {
  const pathname = path.split(/[?#]/)[0] ?? path;
  if (inArea(pathname, "/console")) return role === "operator";
  if (inArea(pathname, "/crew")) return true;
  return false;
}
