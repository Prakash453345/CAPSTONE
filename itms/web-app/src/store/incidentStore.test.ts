import { beforeEach, describe, expect, it } from "vitest";
import { useIncidentStore } from "@/store/incidentStore";
import type { Incident } from "@/types";

const candidate = {
  id: "inc-1",
  status: "candidate",
  detectedAt: "2026-09-28T10:00:00Z",
} as Incident;
const confirmed = { ...candidate, status: "confirmed" } as Incident;

beforeEach(() => {
  useIncidentStore.getState().clearReviews();
  useIncidentStore.getState().setIncidents([]);
});

describe("operator reviews vs the stream", () => {
  it("keeps a confirmation while the stream still says candidate", () => {
    const s = useIncidentStore.getState();
    s.setIncidents([candidate]);
    s.applyReview(confirmed);
    s.setIncidents([candidate]); // next provider tick, not caught up
    expect(useIncidentStore.getState().incidents).toEqual([confirmed]);
  });

  it("hands back to the stream once it reports the outcome", () => {
    const s = useIncidentStore.getState();
    s.applyReview(confirmed);
    const resolved = { ...candidate, status: "resolved" } as Incident;
    s.setIncidents([resolved]);
    expect(useIncidentStore.getState().incidents).toEqual([resolved]);
    expect(useIncidentStore.getState().reviews).toEqual({});
  });

  it("forgets reviews when the data source changes", () => {
    const s = useIncidentStore.getState();
    s.applyReview(confirmed);
    s.clearReviews();
    s.setIncidents([candidate]);
    expect(useIncidentStore.getState().incidents).toEqual([candidate]);
  });
});
