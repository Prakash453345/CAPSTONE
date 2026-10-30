import { describe, expect, it } from "vitest";
import { canOpen, homeFor, parseRole } from "./roles";

describe("roles", () => {
  it("sends each role to its own home", () => {
    expect(homeFor("operator")).toBe("/console");
    expect(homeFor("responder")).toBe("/crew");
  });

  it("lets operators open both areas but crews only their own", () => {
    expect(canOpen("operator", "/console/traffic")).toBe(true);
    expect(canOpen("operator", "/crew")).toBe(true);
    expect(canOpen("responder", "/crew")).toBe(true);
    expect(canOpen("responder", "/console")).toBe(false);
    expect(canOpen("responder", "/console/emergency?x=1#y")).toBe(false);
  });

  it("does not confuse look-alike paths with an area", () => {
    expect(canOpen("responder", "/consolex")).toBe(false);
    expect(canOpen("operator", "/consolex")).toBe(false);
    expect(canOpen("operator", "/crewway")).toBe(false);
  });

  it("treats anything but responder as operator, so a missing role never grants less than before", () => {
    expect(parseRole("responder")).toBe("responder");
    expect(parseRole("operator")).toBe("operator");
    expect(parseRole(undefined)).toBe("operator");
    expect(parseRole("admin")).toBe("operator");
  });
});
