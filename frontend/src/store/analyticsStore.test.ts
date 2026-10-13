import { describe, expect, it } from "vitest";
import {
  appendSample,
  sampleSnapshot,
  telemetryCsv,
  type TelemetrySample,
} from "./analyticsStore";
import type { TrafficSnapshot } from "@/services/traffic/types";
const sample: TelemetrySample = {
  at: 1000,
  vehicles: 0,
  congestion: 0,
  speed: null,
  signals: 7,
  anomalies: 0,
  emergencies: 0,
};
const snapshot: TrafficSnapshot = {
  timestamp: new Date(1000).toISOString(),
  vehicles: [],
  intersections: [],
  incidents: [],
  anomalies: [],
  emergencyRequests: [],
  roadCongestion: {},
  events: [],
  summary: {
    operational: true,
    vehicleCount: 0,
    congestion: 0.2,
    signalsOnline: 7,
    signalsTotal: 7,
    lastUpdate: new Date(1000).toISOString(),
  },
};
describe("session observations", () => {
  it("does not turn missing speed into zero or sample stale/offline state", () => {
    expect(sampleSnapshot(snapshot)).toMatchObject({
      speed: null,
      congestion: 20,
      vehicles: 0,
    });
    expect(
      sampleSnapshot({
        ...snapshot,
        summary: { ...snapshot.summary, operational: false },
      }),
    ).toBeNull();
    expect(
      sampleSnapshot({
        ...snapshot,
        summary: { ...snapshot.summary, lastUpdate: null },
      }),
    ).toBeNull();
  });
  it("limits cadence and memory and rejects out-of-order samples", () => {
    const history = [sample];
    expect(appendSample(history, { ...sample, at: 1500 })).toBe(history);
    expect(appendSample(history, { ...sample, at: 999 })).toBe(history);
    expect(appendSample(history, { ...sample, at: 2000 })).toHaveLength(2);
    expect(appendSample(history, { ...sample, at: 2_000_000 })).toEqual([
      { ...sample, at: 2_000_000 },
    ]);
  });
  it("exports measured fields with missing data left blank", () => {
    expect(telemetryCsv([sample])).toContain(
      "1970-01-01T00:00:01.000Z,0,0.00,,7,0,0",
    );
    expect(telemetryCsv([]).split("\n")).toHaveLength(1);
  });
});
