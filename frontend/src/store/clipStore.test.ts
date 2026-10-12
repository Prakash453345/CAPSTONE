import { beforeEach, describe, expect, it } from "vitest";
import { clipNotifications, needsReview, useClipStore } from "./clipStore";
import type { Clip } from "@/services/traffic/clips";

function clip(over: Partial<Clip> = {}): Clip {
  return {
    id: "c1", filename: "crash.mp4", edgeId: "E1", roadName: "MG Road", submittedMs: 1000,
    status: "QUEUED", progress: 0, videoUrl: "/api/v1/clips/c1/video", snapshotUrl: null,
    anomalyType: null, severity: null, confidence: null, flaggedAtS: null, reasons: [],
    findings: [], timeline: {}, detectors: [], durationS: null, error: "", review: null,
    reviewedBy: "", reviewNote: "", anomalyId: null, confirmedType: null, confirmedSeverity: null,
    ...over,
  };
}

const finding = { status: "DONE" as const, anomalyType: "accident" as const, severity: "high" as const, confidence: 0.9, review: "PENDING" as const };

describe("clip store", () => {
  beforeEach(() => useClipStore.getState().reset());

  it("keeps clips newest first and replaces a clip on upsert", () => {
    const s = useClipStore.getState();
    s.setClips([clip({ id: "old", submittedMs: 1 }), clip({ id: "new", submittedMs: 5 })]);
    s.upsert(clip({ id: "old", submittedMs: 1, status: "ANALYSING" }));
    s.upsert(clip({ id: "newest", submittedMs: 9 }));
    expect(useClipStore.getState().clips.map((c) => [c.id, c.status])).toEqual([
      ["newest", "QUEUED"], ["new", "QUEUED"], ["old", "ANALYSING"],
    ]);
  });

  it("only a finished finding still awaiting a person needs review", () => {
    expect(needsReview(clip(finding))).toBe(true);
    expect(needsReview(clip({ ...finding, review: "REJECTED" }))).toBe(false);
    expect(needsReview(clip({ status: "DONE" }))).toBe(false);
    expect(needsReview(clip({ status: "ANALYSING" }))).toBe(false);
  });
});

describe("clip notifications", () => {
  it("announces a finding when an analysis finishes, as critical for a serious one", () => {
    const [n, ...rest] = clipNotifications([clip({ status: "ANALYSING" })], [clip(finding)], 42);
    expect(rest).toEqual([]);
    expect(n).toMatchObject({ kind: "clip-finding", tone: "critical", title: "Accident spotted on MG Road", atMs: 42 });
  });

  it("says so when a video looks normal, and warns when one fails", () => {
    expect(clipNotifications([clip()], [clip({ status: "DONE" })], 1)[0]).toMatchObject({ tone: "ok", title: "Nothing unusual on MG Road" });
    expect(clipNotifications([clip()], [clip({ status: "FAILED", error: "cannot open video" })], 1)[0]).toMatchObject({
      kind: "clip-failed",
      message: "crash.mp4: cannot open video",
    });
  });

  it("stays quiet for clips that were already finished, or first seen finished (a reload)", () => {
    expect(clipNotifications([clip(finding)], [clip(finding)], 1)).toEqual([]);
    expect(clipNotifications([], [clip(finding)], 1)).toEqual([]);
    expect(clipNotifications([clip()], [clip({ status: "ANALYSING", progress: 0.5 })], 1)).toEqual([]);
  });
});
