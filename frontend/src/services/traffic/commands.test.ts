import { afterEach, describe, expect, it, vi } from "vitest";
import { postCommand, setDemoCommandHandler } from "./commands";
import { useSystemStore } from "@/store/systemStore";
afterEach(() => {
  vi.unstubAllGlobals();
  useSystemStore.setState({
    dataMode: "simulation",
    connectionStatus: "offline",
  });
});
describe("operator command boundary", () => {
  it("never posts demo or disconnected commands to the real backend", async () => {
    setDemoCommandHandler(null);
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    useSystemStore.setState({
      dataMode: "simulation",
      connectionStatus: "online",
    });
    await expect(
      postCommand({ event_type: "EmergencyCommand", payload: {} }),
    ).rejects.toThrow("demo simulation is not running");

    const handler = vi.fn(() => ({ published: true, topic: "demo", message_id: "m" }));
    setDemoCommandHandler(handler);
    await expect(postCommand({ event_type: "EmergencyCommand", payload: {} })).resolves.toMatchObject({ message_id: "m" });
    expect(handler).toHaveBeenCalledTimes(1);
    setDemoCommandHandler(null);
    useSystemStore.setState({
      dataMode: "live",
      connectionStatus: "reconnecting",
    });
    await expect(
      postCommand({ event_type: "EmergencyCommand", payload: {} }),
    ).rejects.toThrow("not connected");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("preserves the existing command API shape when live", async () => {
    useSystemStore.setState({ dataMode: "live", connectionStatus: "online" });
    const result = {
      published: true,
      topic: "commands.operator",
      message_id: "1-0",
    };
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal("fetch", fetch);
    const cmd = {
      event_type: "EmergencyCommand",
      payload: { request_id: "r1" },
    };
    expect(await postCommand(cmd)).toEqual(result);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/commands",
      expect.objectContaining({ method: "POST", body: JSON.stringify(cmd) }),
    );
  });
});
