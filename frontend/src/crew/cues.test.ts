import { describe, expect, it } from "vitest";
import type { Maneuver } from "./plan";
import { cueFor } from "./cues";

const turn: Maneuver = { id: "m1", atM: 900, kind: "turn", side: "left", sharp: false, road: "MG Road", text: "Turn left onto MG Road" };

describe("cueFor", () => {
  it("says nothing until a maneuver is within the first band", () => {
    expect(cueFor(turn, 900)).toBeNull();
    expect(cueFor(turn, 501)).toBeNull();
  });

  it("warns at each band, nearest band only", () => {
    expect(cueFor(turn, 480)).toEqual({ key: "m1:500", text: "In 480 m, turn left onto MG Road" });
    expect(cueFor(turn, 150)).toEqual({ key: "m1:200", text: "In 150 m, turn left onto MG Road" });
    expect(cueFor(turn, 40)).toEqual({ key: "m1:60", text: "Turn left onto MG Road" });
  });

  it("gives the same key for the same band, so it is spoken once", () => {
    expect(cueFor(turn, 450)!.key).toBe(cueFor(turn, 300)!.key);
    expect(cueFor(turn, 190)!.key).not.toBe(cueFor(turn, 300)!.key);
  });

  it("never announces the start, and words the arrival differently", () => {
    expect(cueFor({ ...turn, kind: "depart" }, 10)).toBeNull();
    const arrive: Maneuver = { ...turn, id: "z", kind: "arrive", text: "Arrive at the destination" };
    expect(cueFor(arrive, 300)!.text).toBe("Destination in 300 m");
    expect(cueFor(arrive, 30)!.text).toBe("You are arriving at the destination");
  });
});
