import { useEffect, useState } from "react";
import { Check, Hospital, Loader2 } from "lucide-react";
import { CommandError, postCommand } from "@/services/traffic/commands";
import { mmss } from "@/components/console/words";
import { useCrewStore, type HospitalMission } from "@/store/crewStore";
import { cn } from "@/utils/cn";

/**
 * The patient leg. When an ambulance reaches the scene the system lists the
 * hospitals it can reach, fastest first by live traffic, and picks the first;
 * the crew confirms it or chooses another (the patient may need a particular
 * one, or the family may ask). On the way they can still change it, and the
 * route is re-planned from where the ambulance is.
 */
export function HospitalCard({
  mission,
  variant,
}: {
  mission: HospitalMission;
  /** "choose": at the scene, covering the map. "enroute": a compact card while driving. */
  variant: "choose" | "enroute";
}) {
  const [picked, setPicked] = useState(mission.chosenId || mission.recommendedId);
  const [open, setOpen] = useState(variant === "choose");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setPicked(mission.chosenId || mission.recommendedId), [mission.chosenId, mission.recommendedId]);
  useEffect(() => setOpen(variant === "choose"), [variant]);

  const chosen = mission.options.find((o) => o.facilityId === mission.chosenId);
  const pickedOption = mission.options.find((o) => o.facilityId === picked);

  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await postCommand({
        event_type: "CrewHospitalChoice",
        payload: { unit_id: mission.unitId, facility_id: picked, requested_at: Date.now() },
      });
      setOpen(false);
    } catch (err) {
      setError(
        err instanceof CommandError && err.status === 0
          ? "No connection to dispatch. Try again."
          : "Dispatch didn't get that. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (mission.options.length === 0) {
    return (
      <section className="pointer-events-auto rounded-[22px] bg-surface-raised p-4 shadow-elevation-3">
        <p className="text-[15px] font-semibold">No hospital reachable by road</p>
        <p className="mt-1 text-[13px] text-muted-foreground">Call the control room for instructions.</p>
      </section>
    );
  }

  return (
    <section
      aria-label="Hospital"
      className={cn(
        "pointer-events-auto overflow-hidden rounded-[22px] bg-surface-raised shadow-elevation-3",
        variant === "choose" && "ring-1 ring-status-ok/40",
      )}
    >
      <div className="flex items-center gap-3 px-4 pb-2 pt-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-status-ok-muted text-status-ok">
          <Hospital className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[17px] font-semibold leading-tight">
            {variant === "choose" ? "Take the patient to" : "Patient on board"}
          </p>
          <p className="text-[13px] leading-snug text-muted-foreground">
            {variant === "choose"
              ? "Fastest first by live traffic. If you don't choose, the fastest is picked in 45 s."
              : `To ${chosen?.name ?? "hospital"}`}
          </p>
        </div>
        {variant === "enroute" && !open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="h-9 shrink-0 rounded-full bg-surface-fill px-3.5 text-[14px] font-medium text-primary hover:bg-muted"
          >
            Change
          </button>
        )}
      </div>

      {open && (
        <div className="space-y-3 px-4 pb-4 pt-1">
          <ul role="radiogroup" aria-label="Hospitals" className="divide-y divide-border/70 overflow-hidden rounded-2xl bg-surface-fill">
            {mission.options.map((o, i) => {
              const on = o.facilityId === picked;
              return (
                <li key={o.facilityId}>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => setPicked(o.facilityId)}
                    className="flex w-full items-center gap-3 px-3 py-3 text-left"
                  >
                    <span
                      className={cn(
                        "grid size-6 shrink-0 place-items-center rounded-full border-2",
                        on ? "border-primary bg-primary text-primary-foreground" : "border-input",
                      )}
                    >
                      {on && <Check className="size-3.5" strokeWidth={3} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-medium">{o.name}</span>
                      {i === 0 && <span className="text-[12px] font-medium text-status-ok">Fastest</span>}
                      {o.facilityId === mission.chosenId && i !== 0 && (
                        <span className="text-[12px] text-muted-foreground">Current</span>
                      )}
                    </span>
                    <span className="tabular shrink-0 text-[15px] font-semibold">{mmss(o.etaS)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {error && (
            <p role="alert" className="rounded-xl bg-status-critical-muted px-3 py-2 text-[13px] text-status-critical">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            {variant === "enroute" && (
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="h-12 flex-1 rounded-2xl bg-surface-fill text-[15px] font-medium hover:bg-muted"
              >
                Keep
              </button>
            )}
            <button
              type="button"
              disabled={busy || !pickedOption || (variant === "enroute" && picked === mission.chosenId)}
              onClick={() => void go()}
              className="flex h-12 flex-[2] items-center justify-center gap-2 rounded-2xl bg-primary text-[16px] font-semibold text-primary-foreground transition-[filter,opacity] hover:brightness-105 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-5 animate-spin" />}
              {pickedOption ? `Go to ${pickedOption.name}` : "Choose a hospital"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** This unit's patient leg, while it is still open. */
export function useMyHospital(unitId: string | null): HospitalMission | null {
  const mission = useCrewStore((s) => (unitId ? s.hospital[unitId] : undefined));
  return mission && mission.state !== "done" ? mission : null;
}
