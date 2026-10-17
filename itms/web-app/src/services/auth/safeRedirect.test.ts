import { describe, expect, it } from "vitest";
import { safeNext } from "./safeRedirect";

describe("safeNext", () => {
  it("keeps console paths, with query and hash", () => {
    expect(safeNext("/console")).toBe("/console");
    expect(safeNext("/console/map")).toBe("/console/map");
    expect(safeNext("/console/traffic?road=12#top")).toBe("/console/traffic?road=12#top");
  });

  it("keeps crew-page paths too, but not look-alikes", () => {
    expect(safeNext("/drive")).toBe("/drive");
    expect(safeNext("/drive?unit=EV-001")).toBe("/drive?unit=EV-001");
    expect(safeNext("/driveway")).toBe("/console");
    expect(safeNext("/drive-evil")).toBe("/console");
  });

  it("uses the fallback it is given when the target is not usable", () => {
    expect(safeNext("https://evil.example", "/drive")).toBe("/drive");
    expect(safeNext(null, "/drive")).toBe("/drive");
    expect(safeNext("/console/map", "/drive")).toBe("/console/map");
  });

  it("falls back to the console when there is nothing usable", () => {
    expect(safeNext(null)).toBe("/console");
    expect(safeNext(undefined)).toBe("/console");
    expect(safeNext("")).toBe("/console");
  });

  it.each([
    "https://evil.example/console",
    "//evil.example/console",
    "///evil.example",
    "/\\evil.example",
    "/console\\..\\..",
    "javascript:alert(1)",
    "console/map",
    "/consolex",
    "/console-evil",
    "/login",
    "/",
    "/console\n/map",
    "/console\u0000",
    "http://localhost/console",
  ])("rejects %j", (raw) => {
    expect(safeNext(raw)).toBe("/console");
  });
});
