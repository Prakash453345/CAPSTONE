import { useEffect, useState } from "react";
import { Ambulance, Flame, Loader2, ShieldAlert, X } from "lucide-react";
import { CommandError, postCommand } from "@/services/traffic/commands";
import { roadLabel } from "@/data/network";
import { useCrewStore, type CrewOffer } from "@/store/crewStore";
import { cn } from "@/utils/cn";

/**
 * The incoming call. Dispatch offers an incident to the nearest crew of the
 * kind it needs, and this is where that crew answers.
 *
 * It is deliberately the loudest thing on the page and it covers the map: a
 * driver glancing down has about twenty seconds to decide, and a subtle banner
 * is a missed call. Accept and Decline are far apart for the same reason —
 * this is read at a wheel, not at a desk.
 *
 * Declining is a first-class answer, not a failure: the call goes straight to
 * the next nearest crew, so a driver who is out of the vehicle or already busy
 * should decline rather than let it time out and cost the patient those
 * seconds.
 */

const KIND_ICON: Record<string, typeof Ambulance> = {
  ambulance: Ambulance,
  fire_truck: Flame,
  police: ShieldAlert,
};

const KIND_LABEL: Record<string, string> = {
  ambulance: "Ambulance",
  fire_truck: "Fire",
  police: "Police",
};

function etaText(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec away`;
  return `${Math.round(seconds / 60)} min away`;
}

export function OfferCard({ offer }: { offer: CrewOffer }) {
  const clearOffer = useCrewStore((s) => s.clearOffer);
  const [busy, setBusy] = useState<null | "accept" | "decline">(null);
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState(() =>
    Math.max(0, Math.ceil((offer.expiresAtMs - Date.now()) / 1000)),
  );

  // The countdown is the crew's only cue that the call is about to move on.
  useEffect(() => {
    const id = window.setInterval(() => {
      setLeft(Math.max(0, Math.ceil((offer.expiresAtMs - Date.now()) / 1000)));
    }, 250);
    return () => window.clearInterval(id);
  }, [offer.expiresAtMs]);

  // When it runs out the server has already passed the call on; drop the card
  // rather than leave a button that will be refused.
  useEffect(() => {
    if (left === 0) clearOffer(offer.unitId);
  }, [left, clearOffer, offer.unitId]);

  const answer = async (accept: boolean) => {
    setBusy(accept ? "accept" : "decline");
    setError(null);
    try {
      await postCommand({
        event_type: "CrewOfferResponse",
        payload: { offer_id: offer.offerId, accept, requested_at: Date.now() },
      });
      // The stream clears it too; doing it here means the card goes away on
      // the tap instead of a round-trip later.
      clearOffer(offer.unitId);
    } catch (err) {
      setError(
        err instanceof CommandError && err.status === 0
          ? "No connection to dispatch. Try again."
          : "Dispatch didn't get that. Try again.",
      );
      setBusy(null);
    }
  };

  const Icon = KIND_ICON[offer.kind] ?? Ambulance;
  const road = roadLabel(offer.edgeId);
  const urgent = left <= 8;

  return (
    <div
      role="alertdialog"
      aria-label="Incoming call"
      className="pointer-events-auto absolute inset-x-3 top-3 z-20 animate-sheet-in overflow-hidden rounded-[22px] bg-surface-raised shadow-elevation-3 ring-1 ring-primary/40 lg:left-auto lg:right-4 lg:top-4 lg:w-[400px]"
    >
      <div className="flex items-center gap-3 px-4 pb-1 pt-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary/15 text-primary">
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[17px] font-semibold leading-tight">Incoming call</p>
          <p className="truncate text-[13px] text-muted-foreground">
            {KIND_LABEL[offer.kind] ?? offer.kind} · {etaText(offer.etaS)}
          </p>
        </div>
        <span
          aria-live="off"
          className={cn(
            "rounded-full px-2.5 py-1 font-mono text-sm tabular-nums",
            urgent ? "bg-status-warn-muted text-status-warn" : "bg-muted text-muted-foreground",
          )}
        >
          {left}s
        </span>
      </div>

      <div className="space-y-3 p-4">
        <div className="rounded-2xl bg-surface-fill px-3 py-2.5">
          <p className="text-[12px] text-muted-foreground">Go to</p>
          <p className="truncate text-[17px] font-semibold">{road}</p>
        </div>

        {error && (
          <p role="alert" className="rounded-xl bg-status-critical-muted px-3 py-2 text-[13px] text-status-critical">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            className="flex h-12 flex-1 items-center justify-center gap-1.5 rounded-2xl bg-surface-fill text-[15px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void answer(false)}
          >
            {busy === "decline" ? <Loader2 className="size-4 animate-spin" /> : <X className="size-4" />}
            Decline
          </button>
          <button
            type="button"
            className="flex h-12 flex-[2] items-center justify-center gap-2 rounded-2xl bg-status-ok text-[16px] font-semibold text-white transition-[filter] hover:brightness-105 disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void answer(true)}
          >
            {busy === "accept" && <Loader2 className="size-4 animate-spin" />}
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}

/** The signed-in crew's open offer, if they have one. */
export function useMyOffer(unitId: string | null): CrewOffer | null {
  const offers = useCrewStore((s) => s.offers);
  return unitId ? (offers[unitId] ?? null) : null;
}
