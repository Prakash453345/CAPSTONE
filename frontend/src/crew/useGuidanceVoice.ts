import { useEffect, useRef } from "react";
import { cueFor } from "@/crew/cues";
import { formatDistance } from "@/crew/plan";
import type { Mission } from "@/crew/useMission";

export const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";

export function say(text: string, urgent = false) {
  if (!canSpeak) return;
  try {
    // An urgent warning must not wait behind a queue of older instructions.
    if (urgent) window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-IN";
    u.rate = 1.05;
    window.speechSynthesis.speak(u);
  } catch {
    // no voice available: the on-screen instruction is still there
  }
}

/**
 * Speaks the guidance a crew should not have to look down for: each turn as
 * it approaches (at 500 m, 200 m and 60 m), critical hazards, signals that are
 * held for them or are not safe to run, a changed route, and arrival. Each
 * warning is spoken once.
 */
export function useGuidanceVoice(mission: Mission | null, enabled: boolean) {
  const spoken = useRef(new Set<string>());
  const requestId = useRef<string | null>(null);
  const routeKey = useRef("");

  useEffect(() => {
    if (!enabled && canSpeak) window.speechSynthesis.cancel();
  }, [enabled]);
  useEffect(() => () => {
    if (canSpeak) window.speechSynthesis.cancel();
  }, []);

  useEffect(() => {
    if (!enabled || !mission) return;
    if (requestId.current !== mission.request.id) {
      requestId.current = mission.request.id;
      routeKey.current = mission.plan?.edgeIds.join(",") ?? "";
      spoken.current = new Set();
    }
    if (!mission.underway) return;
    const once = (key: string, text: string, urgent = false) => {
      if (spoken.current.has(key)) return;
      spoken.current.add(key);
      say(text, urgent);
    };

    const key = mission.plan?.edgeIds.join(",") ?? "";
    if (key && routeKey.current && key !== routeKey.current) {
      routeKey.current = key;
      spoken.current = new Set();
      say("Route updated", true);
    }

    if (mission.arrived) return once("arrived", "You have arrived at the destination");

    if (mission.offRouteM > 60) return once(`off:${Math.round(mission.alongM / 100)}`, "You are off the planned route", true);

    if (mission.next) {
      const cue = cueFor(mission.next, mission.nextDistM);
      if (cue) once(cue.key, cue.text);
    }
    for (const h of mission.hazards) {
      if (h.tone === "critical" && h.distM < 1200) once(`hazard:${h.id}`, `${h.title}, ${formatDistance(h.distM)} ahead`, true);
    }
    const s = mission.signals[0];
    if (s && s.status === "held" && s.distM < 350) once(`held:${s.junctionId}`, `Green held at ${s.name}`);
    if (s && (s.status === "red" || s.status === "fault") && s.distM < 250) {
      once(`${s.status}:${s.junctionId}`, s.status === "red" ? `Red signal ahead at ${s.name}. Slow down.` : `Signal fault at ${s.name}. Proceed with caution.`, true);
    }
  }, [mission, enabled]);
}
