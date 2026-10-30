import { useEffect, useRef } from "react";
import { roadLabel } from "@/data/network";
import { say } from "@/crew/useGuidanceVoice";
import { isTerminalRequest } from "@/store/emergencyStore";
import type { EmergencyRequest } from "@/types";

/** The pattern a phone buzzes in when dispatch sends a call: long enough to notice on a dashboard mount. */
export const CALL_VIBRATION = [300, 150, 300, 150, 600];

/** Whether `request` is a call this crew has not been told about yet. A call
 *  that was already live when the page opened counts as known: reloading
 *  mid-mission must not buzz and speak as if dispatch had just called. */
export function isFreshCall(request: EmergencyRequest | null, known: ReadonlySet<string>): boolean {
  return Boolean(request && !isTerminalRequest(request) && !known.has(request.id));
}

/** What is said aloud for a new call. */
export function callAnnouncement(request: Pick<EmergencyRequest, "destinationEdge">): string {
  return `New call. Go to ${roadLabel(request.destinationEdge)}.`;
}

/**
 * Tells the crew when dispatch sends them a call, the way a ride-hailing app
 * alerts its driver: the phone vibrates and, with voice on, the destination is
 * read out. The crew page is already live over the same stream as the console,
 * so the call arrives the moment dispatch assigns this unit; this makes sure
 * the crew notices it without looking at the screen.
 */
export function useNewCallAlert(request: EmergencyRequest | null, voice: boolean) {
  const known = useRef(new Set<string>());
  const primed = useRef(false);

  useEffect(() => {
    if (!primed.current) {
      // First look at this page: whatever is already there is not news.
      primed.current = true;
      if (request) known.current.add(request.id);
      return;
    }
    if (!request || !isFreshCall(request, known.current)) return;
    known.current.add(request.id);
    try {
      navigator.vibrate?.(CALL_VIBRATION);
    } catch {
      // no vibration motor, or the browser blocked it: the card on screen is still there
    }
    if (voice) say(callAnnouncement(request), true);
  }, [request, voice]);
}
