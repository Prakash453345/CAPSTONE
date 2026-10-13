import { describe, expect, it } from "vitest";
import { MAX_SPLIT_RATIO, MIN_SPLIT_RATIO, clampSplitRatio } from "@/utils/splitRatio";

describe("clampSplitRatio", () => {
  it("passes a value already inside range through unchanged", () => {
    expect(clampSplitRatio(0.4)).toBe(0.4);
  });

  it("clamps below the minimum and above the maximum", () => {
    expect(clampSplitRatio(0.01)).toBe(MIN_SPLIT_RATIO);
    expect(clampSplitRatio(0.99)).toBe(MAX_SPLIT_RATIO);
  });

  it("defaults to 0.5 for null/undefined/empty string (localStorage's 'nothing saved yet')", () => {
    expect(clampSplitRatio(null)).toBe(0.5);
    expect(clampSplitRatio(undefined)).toBe(0.5);
    expect(clampSplitRatio("")).toBe(0.5);
  });

  it("defaults to 0.5 for non-numeric input rather than trusting Number()'s coercion", () => {
    // Number(null) and Number("") are both 0 -- a false-finite trap the
    // null/empty-string guard above must intercept before this branch.
    expect(clampSplitRatio("not-a-number")).toBe(0.5);
    expect(clampSplitRatio(NaN)).toBe(0.5);
  });

  it("accepts a numeric string, as read back from localStorage", () => {
    expect(clampSplitRatio("0.35")).toBe(0.35);
  });
});
