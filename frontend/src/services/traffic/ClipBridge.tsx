import { useEffect } from "react";
import { fetchClips } from "@/services/traffic/clips";
import { clipNotifications, isPending, useClipStore } from "@/store/clipStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useSystemStore } from "@/store/systemStore";

const FAST_MS = 2_000; // while a video is queued or being analysed
const SLOW_MS = 15_000;

/**
 * Headless: keeps `clipStore` in step with api-service's `/v1/clips` while in
 * Live mode, polling quickly while any video is still being analysed, and
 * notifies when one finishes. Polling rather than the WebSocket: the clip
 * list is small, and a poll also picks up clips other operators uploaded.
 */
export function ClipBridge() {
  const dataMode = useSystemStore((s) => s.dataMode);

  useEffect(() => {
    const store = useClipStore.getState();
    store.reset();
    if (dataMode !== "live") return;
    let timer: number | undefined;
    let stopped = false;
    const controller = new AbortController();

    const poll = async () => {
      let next = SLOW_MS;
      try {
        const clips = await fetchClips(controller.signal);
        const before = useClipStore.getState().clips;
        useNotificationStore.getState().push(clipNotifications(before, clips, Date.now()));
        useClipStore.getState().setClips(clips);
        if (clips.some(isPending)) next = FAST_MS;
      } catch {
        /* backend away: the connection chip already says so; keep trying */
      }
      if (!stopped) timer = window.setTimeout(poll, next);
    };
    void poll();
    // an upload elsewhere in the console wants a fast poll straight away
    const unsub = useClipStore.subscribe((s, prev) => {
      if (s.clips.some(isPending) && !prev.clips.some(isPending)) {
        window.clearTimeout(timer);
        timer = window.setTimeout(poll, FAST_MS);
      }
    });
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
      unsub();
    };
  }, [dataMode]);

  return null;
}
