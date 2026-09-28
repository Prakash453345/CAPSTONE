import type { SignalState, VehicleType } from "@/types";

export const VEHICLE_COLOR: Record<VehicleType, string> = {
  car: "#5fd0ff",
  bus: "#b78bff",
  truck: "#ffd27f",
  motorcycle: "#7ee0c0",
  ambulance: "#ff5470",
};

export const SIGNAL_COLOR: Record<SignalState, string> = {
  red: "#e5484d",
  yellow: "#f5b83d",
  green: "#46c46a",
};

export const SEVERITY_COLOR = {
  low: "#f5b83d",
  medium: "#e0902a",
  high: "#e5622a",
  critical: "#e5484d",
} as const;

/** Operator / detector anomaly colours, keyed by anomaly severity. */
export const ANOMALY_SEVERITY_COLOR = {
  low: "#f5b83d",
  medium: "#e6902a",
  high: "#e5622a",
  blocked: "#e5484d",
} as const;

export const CONGESTION_STOPS: Array<[number, string]> = [
  [0, "#3f6b52"],
  [0.4, "#e0a12a"],
  [0.7, "#e0662a"],
  [1, "#c0392b"],
];

/** The recommended route for every emergency mission — one constant "this is
 *  the path" colour (a classic radium/neon green), not the per-mission hash
 *  used for vehicle markers. A route needs to read as "the optimal route"
 *  instantly regardless of which mission it belongs to; hashing its colour
 *  the same way as the vehicle marker made every mission's route a
 *  different, unpredictable hue and none of them reliably legible. */
export const EV_ROUTE_COLOR = "#39ff14";

/** Green-corridor preemption — shared with `SignalLayer`'s ring around a
 *  currently-held junction, so the map has exactly one consistent "this is
 *  for an emergency vehicle" accent, distinct from ordinary road/signal
 *  colours and from any mission's own hash colour. */
export const CORRIDOR_ACCENT_COLOR = "#5fd0ff";
