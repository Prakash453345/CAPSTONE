import { PRESET_UNITS } from "@/store/emergencyStore";
import type { AnomalyKind, EmergencyRequest, IncidentType } from "@/types";
import type { Tone } from "@/components/console/tone";

/**
 * How the console talks about things. Kept in one place so a disruption,
 * a unit or the network's mood reads the same on every page.
 */

export function networkMood(congestion: number | null): { headline: string; tone: Tone } {
  if (congestion === null) return { headline: "Waiting for traffic data", tone: "neutral" };
  if (congestion < 0.25) return { headline: "Traffic is flowing freely", tone: "ok" };
  if (congestion < 0.45) return { headline: "Traffic is moving, slower in places", tone: "ok" };
  if (congestion < 0.65) return { headline: "Traffic is heavy in places", tone: "warn" };
  return { headline: "The corridor is congested", tone: "critical" };
}

export function congestionTone(v: number | undefined): Tone {
  if (v == null) return "neutral";
  return v > 0.6 ? "critical" : v > 0.35 ? "warn" : "ok";
}

export function congestionWord(v: number | undefined): string {
  if (v == null) return "No reading";
  return v > 0.6 ? "Heavy" : v > 0.35 ? "Slow" : "Free flow";
}

const ANOMALY_WORDS: Record<AnomalyKind, string> = {
  accident: "Accident",
  vehicle_breakdown: "Breakdown",
  lane_blockage: "Lane blocked",
  road_obstruction: "Obstruction",
  heavy_congestion: "Heavy congestion",
  stalled_vehicle: "Stalled vehicle",
  fire: "Fire",
  unknown: "Disruption",
};
export const anomalyWord = (k: AnomalyKind) => ANOMALY_WORDS[k] ?? "Disruption";

const INCIDENT_WORDS: Record<IncidentType, string> = {
  breakdown: "breakdown",
  collision: "collision",
  congestion: "congestion",
  unknown: "incident",
};
export const incidentWord = (t: IncidentType) => INCIDENT_WORDS[t] ?? "incident";

export const SOURCE_WORDS: Record<string, string> = {
  operator: "Reported by an operator",
  sumo_injector: "Simulation scenario",
  graph_model: "Detected by the model",
  vision: "Detected on camera",
};

export const STATE_WORDS: Record<EmergencyRequest["state"], { label: string; tone: Tone }> = {
  created: { label: "Requested", tone: "neutral" },
  routing: { label: "Finding a route", tone: "info" },
  route_ready: { label: "Route ready", tone: "info" },
  green_corridor_active: { label: "Corridor active", tone: "ok" },
  in_transit: { label: "On the way", tone: "info" },
  completed: { label: "Arrived", tone: "ok" },
  cancelled: { label: "Stood down", tone: "neutral" },
};

/** "Ambulance 12" for a preset unit, otherwise its id tidied up. */
export function unitName(vehicleId: string): string {
  const preset = PRESET_UNITS.find((u) => u.id === vehicleId);
  if (preset) return preset.callSign;
  const m = /^amb[-_]?0*(\d+)$/i.exec(vehicleId);
  if (m) return `Ambulance ${m[1]}`;
  return vehicleId;
}

/** A duration people read at a glance: "45 s", "3 min", "1 h 5 min". */
export function mmss(seconds: number | undefined | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "–";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}
