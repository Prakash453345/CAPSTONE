import { describe, it, expect } from "vitest";
import { hasFastWebGL } from "./webgl";

describe("hasFastWebGL", () => {
  it("answers false, without throwing, where WebGL can't be created", () => {
    expect(hasFastWebGL()).toBe(false);
    // cached: asking again doesn't probe again
    expect(hasFastWebGL()).toBe(false);
  });
});
