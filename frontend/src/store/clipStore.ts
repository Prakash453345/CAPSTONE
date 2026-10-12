import { create } from "zustand";
import type { Clip } from "@/services/traffic/clips";
import { anomalyWord } from "@/components/console/words";
import type { NotificationEvent } from "@/types";

/**
 * Uploaded road videos and their analysis, newest first. Filled by
 * `ClipBridge` (polling `/v1/clips` in Live mode) and by the upload panel
 * and review form, which `upsert` the clip the API hands back.
 */
interface ClipState {
  clips: Clip[];
  selectedClipId: string | null;
  setClips: (clips: Clip[]) => void;
  upsert: (clip: Clip) => void;
  selectClip: (id: string | null) => void;
  reset: () => void;
}

const newestFirst = (a: Clip, b: Clip) => b.submittedMs - a.submittedMs;

export const useClipStore = create<ClipState>((set) => ({
  clips: [],
  selectedClipId: null,
  setClips: (clips) => set({ clips: [...clips].sort(newestFirst) }),
  upsert: (clip) =>
    set((s) => ({
      clips: [clip, ...s.clips.filter((c) => c.id !== clip.id)].sort(newestFirst),
    })),
  selectClip: (selectedClipId) => set({ selectedClipId }),
  reset: () => set({ clips: [], selectedClipId: null }),
}));

export const isPending = (c: Clip) => c.status === "QUEUED" || c.status === "ANALYSING";
export const needsReview = (c: Clip) => c.status === "DONE" && c.review === "PENDING";

/** Notifications for clips whose analysis finished since the last poll: a
 *  finding to review, or a failure. Clips already finished in `before` (or
 *  unseen until now and already finished: a page reload) raise nothing. */
export function clipNotifications(before: Clip[], after: Clip[], atMs: number): NotificationEvent[] {
  const prev = new Map(before.map((c) => [c.id, c]));
  const out: NotificationEvent[] = [];
  for (const c of after) {
    const was = prev.get(c.id);
    if (!was || !isPending(was) || isPending(c)) continue;
    const road = c.roadName || "the road";
    if (c.status === "FAILED") {
      out.push({
        id: `clip-failed-${c.id}`, kind: "clip-failed", tone: "warn", atMs,
        title: "Video could not be analysed",
        message: `${c.filename}: ${c.error || "analysis failed"}`,
      });
    } else if (needsReview(c) && c.anomalyType) {
      out.push({
        id: `clip-finding-${c.id}`, kind: "clip-finding",
        tone: c.severity === "high" || c.severity === "blocked" ? "critical" : "warn", atMs,
        title: `${anomalyWord(c.anomalyType)} spotted on ${road}`,
        message: `In ${c.filename}, ${Math.round((c.confidence ?? 0) * 100)}% sure. Review it under Incidents.`,
      });
    } else if (c.status === "DONE") {
      out.push({
        id: `clip-clear-${c.id}`, kind: "clip-finding", tone: "ok", atMs,
        title: `Nothing unusual on ${road}`,
        message: `${c.filename} looks like normal traffic.`,
      });
    }
  }
  return out;
}
