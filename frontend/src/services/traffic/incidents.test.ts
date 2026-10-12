import { describe, expect, it } from "vitest";
import { mapIncident } from "./incidents";
const candidate = {
  incident_id: "inc-1",
  intersection_id: "1880441505",
  detected_at: "2026-01-01T00:00:00Z",
  fused_probability: 0.9,
};
describe("detector incident normalization", () => {
  it("maps stream and REST using real junction geometry", () => {
    const result = mapIncident(candidate)!;
    expect(result.status).toBe("candidate");
    expect(result.latitude).toBeGreaterThan(16);
    expect(result.longitude).toBeGreaterThan(80);
    expect(result.severityKnown).toBe(false);
    expect(
      mapIncident({
        ...candidate,
        first_seen_ms: Date.parse(candidate.detected_at),
        state: "CONFIRMED",
        classification: "STALL",
      }),
    ).toMatchObject({ status: "confirmed", type: "breakdown" });
  });
  it("folds a terminal stream event that has no geometry or timestamp of its own", () => {
    expect(
      mapIncident(
        {
          incident_id: "inc-1",
          new_state: "REJECTED",
          fused_probability: null,
        },
        mapIncident(candidate)!,
      ),
    ).toMatchObject({
      status: "resolved",
      resolution: "rejected",
      confidence: 0.9,
    });
  });
  it("rejects unknown locations, invalid timestamps/probabilities and invalid states", () => {
    expect(
      mapIncident({ ...candidate, intersection_id: "missing" }),
    ).toBeNull();
    expect(mapIncident({ ...candidate, detected_at: "bad" })).toBeNull();
    expect(mapIncident({ ...candidate, fused_probability: NaN })).toBeNull();
    expect(mapIncident({ ...candidate, state: "INVALID" })).toBeNull();
  });
});
