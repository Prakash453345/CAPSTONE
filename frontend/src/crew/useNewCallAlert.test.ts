import { describe, expect, it } from "vitest";
import type { EmergencyRequest } from "@/types";
import { callAnnouncement, isFreshCall } from "./useNewCallAlert";

const req = (over: Partial<EmergencyRequest> = {}): EmergencyRequest => ({
  id: "r1",
  vehicleId: "unit-police-3",
  vehicleKind: "police",
  state: "route_ready",
  sourceEdge: "a",
  destinationEdge: "b",
  alternatives: [],
  timeline: [],
  updatedAt: "2026-10-18T10:00:00Z",
  ...over,
});

describe("isFreshCall", () => {
  it("is true for a live call the crew has not heard about", () => {
    expect(isFreshCall(req(), new Set())).toBe(true);
  });
  it("is false once known, for a finished call, and for no call", () => {
    expect(isFreshCall(req(), new Set(["r1"]))).toBe(false);
    expect(isFreshCall(req({ state: "completed" }), new Set())).toBe(false);
    expect(isFreshCall(req({ state: "cancelled" }), new Set())).toBe(false);
    expect(isFreshCall(null, new Set())).toBe(false);
  });
});

describe("callAnnouncement", () => {
  it("names where to go", () => {
    expect(callAnnouncement(req())).toMatch(/^New call\. Go to .+\.$/);
  });
});
