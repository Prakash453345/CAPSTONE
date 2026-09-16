import { create } from "zustand";
import type { TrafficSnapshot } from "@/services/traffic/types";

export interface TelemetrySample {
  at: number;
  vehicles: number;
  congestion: number;
  speed: number | null;
  signals: number;
  anomalies: number;
  emergencies: number;
}
export function sampleSnapshot(snap: TrafficSnapshot): TelemetrySample | null {
  const at = snap.summary.lastUpdate
    ? Date.parse(snap.summary.lastUpdate)
    : NaN;
  if (!Number.isFinite(at) || !snap.summary.operational) return null;
  const speeds = snap.vehicles.map((v) => v.speed).filter(Number.isFinite);
  return {
    at,
    vehicles: snap.vehicles.length,
    congestion: snap.summary.congestion * 100,
    speed: speeds.length
      ? speeds.reduce((a, b) => a + b, 0) / speeds.length
      : null,
    signals: snap.summary.signalsOnline,
    anomalies: snap.anomalies.filter((a) => a.status === "active").length,
    emergencies: snap.emergencyRequests.filter(
      (r) => !["completed", "cancelled"].includes(r.state),
    ).length,
  };
}
export function appendSample(
  history: TelemetrySample[],
  sample: TelemetrySample,
): TelemetrySample[] {
  if (history.length && sample.at - history[history.length - 1].at < 1000)
    return history;
  return [
    ...history.filter((s) => s.at >= sample.at - 30 * 60_000),
    sample,
  ].slice(-1800);
}
export function telemetryCsv(samples: TelemetrySample[]): string {
  return [
    "timestamp,vehicles,mean_occupancy_pct,mean_speed_kmh,signals_reporting,active_anomalies,active_emergencies",
    ...samples.map((s) =>
      [
        new Date(s.at).toISOString(),
        s.vehicles,
        s.congestion.toFixed(2),
        s.speed?.toFixed(2) ?? "",
        s.signals,
        s.anomalies,
        s.emergencies,
      ].join(","),
    ),
  ].join("\n");
}
export const useAnalyticsStore = create<{
  samples: TelemetrySample[];
  ingest: (snap: TrafficSnapshot) => void;
  reset: () => void;
}>((set) => ({
  samples: [],
  ingest: (snap) => {
    const sample = sampleSnapshot(snap);
    if (sample) set((s) => ({ samples: appendSample(s.samples, sample) }));
  },
  reset: () => set({ samples: [] }),
}));
