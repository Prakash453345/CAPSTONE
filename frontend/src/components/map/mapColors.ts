import type { SignalState, VehicleType } from "@/types";

/** Calm, distinguishable hues; the ambulance is the only saturated red. */
export const VEHICLE_COLOR: Record<VehicleType, string> = {
  car: "#6f8fff",
  bus: "#a78bfa",
  truck: "#e8a33d",
  motorcycle: "#34c3a0",
  ambulance: "#ff3b4f",
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

/** Google Maps' live-traffic ramp: free flow → slow → heavy → standstill. */
export const CONGESTION_STOPS: Array<[number, string]> = [
  [0, "#63d668"],
  [0.4, "#ff974d"],
  [0.7, "#f23c32"],
  [1, "#811f1f"],
];

/** A route's stretches by live traffic (crew page), on Google's ramp above. */
export const TRAFFIC_COLOR = { free: "#34b853", slow: "#ff974d", heavy: "#f23c32" } as const;

/** The recommended route for every emergency mission: one constant "this is
 *  the path" colour, not the per-mission hash used for vehicle markers, so a
 *  route reads as "the optimal route" instantly whichever mission it is.
 *
 *  Blue, deliberately outside the traffic ramp above. Roads are coloured
 *  green / orange / red by live congestion, so a green route disappeared into
 *  free-flowing traffic. Blue with a darker outline (the convention Google
 *  Maps uses for directions over its traffic layer) stays legible on every
 *  congestion colour and on both basemap themes. */
export const EV_ROUTE_COLOR = "#1a73e8";
/** Outline under the route line, so it separates from the road beneath. */
export const EV_ROUTE_CASING = "#0b3f8f";
/** Alternatives of the selected mission: same family, lighter, so they read
 *  as "other ways" and never compete with the recommended route. */
export const EV_ROUTE_ALT_COLOR = "#9fc2f7";
export const EV_ROUTE_ALT_CASING = "#4f6f9f";

/** Green-corridor preemption — shared with `SignalLayer`'s ring around a
 *  currently-held junction, so the map has exactly one consistent "this is
 *  for an emergency vehicle" accent, distinct from ordinary road/signal
 *  colours and from any mission's own hash colour. */
export const CORRIDOR_ACCENT_COLOR = "#5fd0ff";
