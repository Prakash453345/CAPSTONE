import { describe, expect, it } from "vitest";
import { classify, rainDensity, trafficAdvice, DEMO_WEATHER } from "@/services/weather/weather";

describe("classify (WMO code + measured rain)", () => {
  it("maps dry codes", () => {
    expect(classify(0)).toBe("clear");
    expect(classify(1)).toBe("clear");
    expect(classify(3)).toBe("cloudy");
    expect(classify(45)).toBe("fog");
  });

  it("maps wet codes by intensity", () => {
    expect(classify(51, 0.2)).toBe("drizzle");
    expect(classify(61, 2)).toBe("rain");
    expect(classify(65, 3)).toBe("heavy-rain");
    expect(classify(63, 9)).toBe("heavy-rain");
    expect(classify(95)).toBe("thunderstorm");
  });

  it("trusts measured rain over a dry code", () => {
    expect(classify(3, 2)).toBe("rain");
    expect(classify(2, 0.3)).toBe("drizzle");
  });
});

describe("rain density and advice", () => {
  it("draws nothing when dry and more for heavier rain", () => {
    expect(rainDensity(DEMO_WEATHER.clear)).toBe(0);
    expect(rainDensity(DEMO_WEATHER.rain)).toBeLessThan(rainDensity(DEMO_WEATHER["heavy-rain"]));
  });

  it("only gives traffic advice when weather matters", () => {
    expect(trafficAdvice(DEMO_WEATHER.clear)).toBeNull();
    expect(trafficAdvice(DEMO_WEATHER.rain)).toMatch(/slower/);
    expect(trafficAdvice(DEMO_WEATHER.fog)).toMatch(/visibility/);
  });
});
