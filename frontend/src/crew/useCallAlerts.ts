import { useEffect, useRef, useState } from "react";
import { roadLabel } from "@/data/network";
import { isTerminalRequest } from "@/store/emergencyStore";
import { useCrewStore, type CrewOffer, type HospitalMission } from "@/store/crewStore";
import type { EmergencyRequest } from "@/types";

/**
 * Web notifications for a crew: a new call assigned to their vehicle, a call
 * they are being asked to take, and the hospital to choose at a scene. They
 * show even when the crew page is in a background tab, with a sound and a
 * vibration on phones, so a driver who glanced away still hears about it.
 *
 * Browsers only allow this on HTTPS (or localhost) and only after the person
 * says yes once; `useAlertPermission` is what the "Turn on call alerts"
 * prompt uses to ask.
 */

export type AlertSupport = "unsupported" | "insecure" | NotificationPermission;

function support(): AlertSupport {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  if (!window.isSecureContext) return "insecure";
  return Notification.permission;
}

export function useAlertPermission(): { state: AlertSupport; ask: () => Promise<void> } {
  const [state, setState] = useState<AlertSupport>(support);
  const ask = async () => {
    if (state !== "default") return;
    try {
      setState(await Notification.requestPermission());
    } catch {
      setState(support());
    }
    unlockSound();
  };
  return { state, ask };
}

let audio: AudioContext | null = null;
/** Browsers only play sound after a tap; the permission button is that tap. */
function unlockSound() {
  try {
    audio ??= new AudioContext();
    void audio.resume();
  } catch {
    audio = null;
  }
}

/** Two short rising tones: distinct from the voice guidance, short enough not to annoy. */
function chime() {
  try {
    if (!audio || audio.state !== "running") return;
    const t0 = audio.currentTime;
    for (const [i, hz] of [880, 1320].entries()) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, t0 + i * 0.18);
      gain.gain.exponentialRampToValueAtTime(0.25, t0 + i * 0.18 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.18 + 0.16);
      osc.connect(gain).connect(audio.destination);
      osc.start(t0 + i * 0.18);
      osc.stop(t0 + i * 0.18 + 0.17);
    }
  } catch {
    // no sound is fine; the notification still shows
  }
}

function notify(title: string, body: string, tag: string) {
  chime();
  try {
    navigator.vibrate?.([220, 120, 220]);
  } catch {
    // not a phone
  }
  if (support() !== "granted") return;
  try {
    const n = new Notification(title, { body, tag, requireInteraction: true });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // Some mobile browsers only allow notifications from a service worker;
    // the in-page card and the sound still tell the crew.
  }
}

/** Fire the notifications for one crew page. Nothing fires for what was
 *  already there when the page opened: only for what arrives while it is open. */
export function useCallAlerts({
  unitName,
  request,
  offer,
  hospital,
}: {
  unitName: string | null;
  request: EmergencyRequest | null;
  offer: CrewOffer | null;
  hospital: HospitalMission | null;
}) {
  const seen = useRef<Set<string> | null>(null);
  // Sound needs one tap on the page first (browser rule); any tap will do.
  useEffect(() => {
    const unlock = () => unlockSound();
    window.addEventListener("pointerdown", unlock, { once: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);
  const keys: string[] = [];
  if (request && !isTerminalRequest(request) && !/-hospital-\d+$/.test(request.id)) keys.push(`call:${request.id}`);
  if (offer) keys.push(`offer:${offer.offerId}`);
  if (hospital?.state === "at_scene") keys.push(`hospital:${hospital.requestId}`);

  useEffect(() => {
    if (seen.current === null) {
      seen.current = new Set(keys);
      return;
    }
    for (const key of keys) {
      if (seen.current.has(key)) continue;
      seen.current.add(key);
      const who = unitName ?? "Your unit";
      if (key.startsWith("call:") && request) {
        notify(`New call for ${who}`, `Go to ${roadLabel(request.destinationEdge)}. Your route is on screen.`, "traffix-call");
      } else if (key.startsWith("offer:") && offer) {
        // When dispatch assigns calls outright the offer is accepted in the
        // same instant; only a call still waiting for an answer is announced
        // as one (the "New call" alert covers the rest).
        const { unitId, offerId, edgeId } = offer;
        window.setTimeout(() => {
          if (useCrewStore.getState().offers[unitId]?.offerId !== offerId) return;
          notify(`Incoming call for ${who}`, `${roadLabel(edgeId)}. Accept or decline on the crew page.`, "traffix-call");
        }, 1500);
      } else if (key.startsWith("hospital:") && hospital) {
        const rec = hospital.options.find((o) => o.facilityId === hospital.recommendedId);
        notify("Choose a hospital", rec ? `Fastest: ${rec.name}. Confirm or pick another.` : "Pick where to take the patient.", "traffix-hospital");
      }
    }
  }, [keys.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps -- the keys are the trigger
}
