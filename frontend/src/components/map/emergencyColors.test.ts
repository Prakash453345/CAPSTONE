import { describe, expect, it } from "vitest";
import { colorForRequest } from "@/components/map/emergencyColors";

describe("colorForRequest", () => {
  it("is stable for the same id", () => {
    const id = "er-abc-123";
    expect(colorForRequest(id)).toBe(colorForRequest(id));
  });

  it("does not depend on any other request existing", () => {
    // unlike a list-position scheme, a single id's colour never needs "the
    // full set of active ids" as input — it can't shift when a sibling
    // mission completes or a new one starts
    const a = colorForRequest("er-1");
    const b = colorForRequest("er-1");
    expect(a).toBe(b);
  });

  it("spreads different ids across the palette", () => {
    const ids = ["er-1", "er-2", "er-3", "er-4", "er-5", "er-6"];
    const colors = new Set(ids.map(colorForRequest));
    expect(colors.size).toBeGreaterThan(1);
  });

  it("returns a css hex colour", () => {
    expect(colorForRequest("er-1")).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
