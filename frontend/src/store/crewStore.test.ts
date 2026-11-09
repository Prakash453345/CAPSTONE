import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCrewStore } from "./crewStore";

const offered = (left: number | undefined) => ({
  offer_id: "off-1", incident_id: "inc-1", kind: "ambulance", edge_id: "E1",
  unit_id: "EV-1", eta_s: 60, state: "offered", asked: [],
  ...(left === undefined ? {} : { expires_in_s: left }),
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-06T10:00:00Z"));
  useCrewStore.setState({ offers: {}, calls: {} });
});
afterEach(() => vi.useRealTimers());

describe("crew offers", () => {
  it("counts down from the time the server says is left, so a re-send does not restart it", () => {
    useCrewStore.getState().applyOffer(offered(25));
    vi.advanceTimersByTime(9_000);
    useCrewStore.getState().applyOffer(offered(16)); // the 3 s re-send, 9 s in
    const offer = useCrewStore.getState().offers["EV-1"];
    expect(offer.offerId).toBe("off-1");
    expect(offer.expiresAtMs - Date.now()).toBe(16_000);
    expect(useCrewStore.getState().calls["inc-1"].expiresAtMs - Date.now()).toBe(16_000);
  });

  it("a page that reloads mid-offer picks the call up from the next re-send", () => {
    useCrewStore.getState().applyOffer(offered(7)); // first thing the fresh page hears
    expect(useCrewStore.getState().offers["EV-1"].expiresAtMs - Date.now()).toBe(7_000);
  });

  it("falls back to the full window when a producer sends no time left", () => {
    useCrewStore.getState().applyOffer(offered(undefined));
    expect(useCrewStore.getState().offers["EV-1"].expiresAtMs - Date.now()).toBe(25_000);
  });

  it("an answered offer clears the card", () => {
    useCrewStore.getState().applyOffer(offered(20));
    useCrewStore.getState().applyOffer({ ...offered(0), state: "accepted" });
    expect(useCrewStore.getState().offers["EV-1"]).toBeUndefined();
    expect(useCrewStore.getState().calls["inc-1"].expiresAtMs).toBe(0);
  });
});
