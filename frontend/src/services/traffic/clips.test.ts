import { afterEach, describe, expect, it, vi } from "vitest";
import { mapClip, reviewClip } from "./clips";
import { useSystemStore } from "@/store/systemStore";

const done = {
  clip_id: "c1",
  filename: "crash.mp4",
  edge_id: "E1",
  road_name: "MG Road",
  submitted_ms: 1_760_000_000_000,
  status: "DONE",
  progress: 1,
  video_url: "/v1/clips/c1/video",
  snapshot_url: "/v1/clips/c1/snapshot",
  anomaly_type: "accident",
  severity: "high",
  confidence: 0.91,
  flagged_at_s: 12.5,
  reasons: ["accident model: 3 of 5 frames at or above 0.50 (peak 0.91)", "accident: starts at high"],
  findings: [
    { anomaly_type: "accident", detector: "accident", severity: "high", confidence: 0.91, start_s: 12.5, end_s: 20, reasons: [] },
    { anomaly_type: "heavy_congestion", detector: "congestion", severity: "low", confidence: 0.6, start_s: 30, end_s: 95, reasons: [] },
  ],
  timeline: { t: [0, 1, 2], accident: [0.1, 0.2, 0.9] },
  detectors: ["vehicles", "accident"],
  duration_s: 96,
  error: "",
  review: "PENDING",
  reviewed_by: "",
  review_note: "",
  anomaly_id: null,
  confirmed_type: null,
  confirmed_severity: null,
};

describe("clip normalization", () => {
  it("maps an analysed clip, routing media through the API base", () => {
    const c = mapClip(done)!;
    expect(c).toMatchObject({
      id: "c1",
      status: "DONE",
      anomalyType: "accident",
      severity: "high",
      flaggedAtS: 12.5,
      review: "PENDING",
      videoUrl: "/api/v1/clips/c1/video",
      snapshotUrl: "/api/v1/clips/c1/snapshot",
    });
    expect(c.findings[1]).toMatchObject({ anomalyType: "heavy_congestion", startS: 30 });
    expect(c.timeline.accident).toEqual([0.1, 0.2, 0.9]);
  });

  it("maps a clip that is still queued, with nothing found yet", () => {
    const c = mapClip({ clip_id: "c2", filename: "a.mp4", status: "QUEUED", video_url: "/v1/clips/c2/video" })!;
    expect(c).toMatchObject({ status: "QUEUED", anomalyType: null, snapshotUrl: null, review: null, findings: [] });
  });

  it("rejects rows without an id", () => {
    expect(mapClip({ status: "DONE" })).toBeNull();
  });
});

describe("clip review", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useSystemStore.setState({ dataMode: "simulation" });
  });

  it("is refused outside Live mode, before any request", async () => {
    useSystemStore.setState({ dataMode: "simulation" });
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await expect(reviewClip("c1", "confirm", "k", { actor: "op" })).rejects.toMatchObject({ status: 409 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends the key, the reviewer and any correction, and maps the answer", async () => {
    useSystemStore.setState({ dataMode: "live" });
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...done, review: "CONFIRMED", confirmed_type: "fire", confirmed_severity: "blocked" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const c = await reviewClip("c1", "confirm", "secret", { actor: "operator:asha", anomalyType: "fire", severity: "blocked" });
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe("/api/v1/clips/c1/confirm");
    expect(init.headers["X-API-Key"]).toBe("secret");
    expect(JSON.parse(init.body)).toEqual({ actor: "operator:asha", note: "", anomaly_type: "fire", severity: "blocked" });
    expect(c).toMatchObject({ review: "CONFIRMED", confirmedType: "fire", confirmedSeverity: "blocked" });
  });

  it("surfaces the API's own reason when a review is refused", async () => {
    useSystemStore.setState({ dataMode: "live" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "this clip was already rejected" }), { status: 409 }),
    ));
    await expect(reviewClip("c1", "confirm", "k", { actor: "op" })).rejects.toMatchObject({
      status: 409,
      detail: "this clip was already rejected",
    });
  });
});
