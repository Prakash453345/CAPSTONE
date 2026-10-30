import { describe, expect, it } from "vitest";
import { formatCount, formatRelative } from "@/utils/format";

describe("formatCount", () => {
  it("thousands-separates and rounds", () => {
    expect(formatCount(12480)).toBe("12,480");
    expect(formatCount(999.6)).toBe("1,000");
    expect(formatCount(0)).toBe("0");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-10T12:00:00.000Z");
  const ago = (secs: number) => new Date(now.getTime() - secs * 1000);

  it("buckets seconds / minutes / hours / days", () => {
    expect(formatRelative(ago(2), now)).toBe("just now");
    expect(formatRelative(ago(30), now)).toBe("30s ago");
    expect(formatRelative(ago(90), now)).toBe("1m ago");
    expect(formatRelative(ago(3 * 3600), now)).toBe("3h ago");
    expect(formatRelative(ago(2 * 86400), now)).toBe("2d ago");
  });

  it("accepts an ISO string and never goes negative", () => {
    expect(formatRelative(now.toISOString(), now)).toBe("just now");
    expect(formatRelative(new Date(now.getTime() + 5000), now)).toBe("just now");
  });
});
