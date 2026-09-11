import type { SignalState, VehicleType } from "@/types";

export const VEHICLE_COLOR: Record<VehicleType, string> = {
  car: "#5fd0ff",
  bus: "#b78bff",
  truck: "#ffd27f",
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
