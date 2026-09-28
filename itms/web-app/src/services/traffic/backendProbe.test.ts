import { describe, expect, it, vi, afterEach } from "vitest";
import { isBackendReachable } from "@/services/traffic/backendProbe";
import { useSystemStore } from "@/store/systemStore";

const initial = useSystemStore.getState();

afterEach(() => {
  vi.unstubAllGlobals();
  useSystemStore.setState({
    dataMode: initial.dataMode,
    dataModeChosen: initial.dataModeChosen,
  });
});

describe("isBackendReachable", () => {
  it("is true when /health answers ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    expect(await isBackendReachable()).toBe(true);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/health");
  });

  it("is false on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    expect(await isBackendReachable()).toBe(false);
  });

  it("is false when the connection is refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("refused")));
    expect(await isBackendReachable()).toBe(false);
  });

  it("gives up rather than hanging on a backend that never answers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) =>
            init.signal?.addEventListener("abort", () =>
              reject(new Error("aborted")),
            ),
          ),
      ),
    );
    expect(await isBackendReachable(10)).toBe(false);
  });
});

describe("startup mode selection", () => {
  it("defaults to simulation so a cold open renders without a backend", () => {
    expect(initial.dataMode).toBe("simulation");
  });

  it("upgrades to live while the operator has not chosen", () => {
    useSystemStore.getState().adoptLiveIfUnchosen();
    expect(useSystemStore.getState().dataMode).toBe("live");
  });

  it("leaves an operator's own choice of demo alone", () => {
    useSystemStore.getState().setDataMode("simulation");
    useSystemStore.getState().adoptLiveIfUnchosen();
    expect(useSystemStore.getState().dataMode).toBe("simulation");
  });
});
