import { describe, expect, it, vi, afterEach } from "vitest";
import { prefersReducedMotion } from "@/utils/motion";

describe("prefersReducedMotion", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is false when matchMedia is unavailable", () => {
    vi.stubGlobal("window", undefined);
    expect(prefersReducedMotion()).toBe(false);
  });

  it("reads the reduced-motion media query", () => {
    vi.stubGlobal("window", {
      matchMedia: (q: string) => ({
        matches: q.includes("prefers-reduced-motion: reduce"),
      }),
    });
    expect(prefersReducedMotion()).toBe(true);
  });
});
