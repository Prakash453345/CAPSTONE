import { CheckCircle2 } from "lucide-react";
import { Panel, PanelHeader, Pill } from "@/components/console/kit";
import { TONE_BG, TONE_DOT, TONE_TEXT } from "@/components/console/tone";
import { formatDistance } from "@/drive/plan";
import type { UpcomingSignal } from "@/drive/situation";
import type { GreenCorridorView } from "@/types";
import { cn } from "@/utils/cn";

/**
 * The signals still ahead, and whether each is being held green for this
 * vehicle. This is what makes an emergency route different from an ordinary
 * one, so it sits right under the turn instruction.
 */
export function CorridorCard({ signals, corridor }: { signals: UpcomingSignal[]; corridor: GreenCorridorView | undefined }) {
  const active = corridor?.status === "active";
  const passed = corridor?.passedIntersections.length ?? 0;
  const total = corridor?.reservations.length ?? 0;

  return (
    <Panel aria-labelledby="corridor-title" className="pointer-events-auto">
      <PanelHeader
        id="corridor-title"
        title="Signals ahead"
        subtitle={total ? `${passed} of ${total} cleared for you` : "No green corridor on this route"}
        actions={<Pill tone={active ? "ok" : "neutral"} dot>{active ? "Corridor active" : corridor ? "Corridor " + corridor.status : "No corridor"}</Pill>}
      />
      {signals.length === 0 ? (
        <p className="flex items-center gap-2 px-5 pb-4 text-[13px] text-muted-foreground">
          <CheckCircle2 className="size-4 text-status-ok" aria-hidden />
          No more signals on this route.
        </p>
      ) : (
        <ol className="px-3 pb-3">
          {signals.map((s) => (
            <li key={s.junctionId} className="flex items-center gap-3 rounded-xl px-2 py-2.5">
              <span
                aria-hidden
                className={cn(
                  "relative grid size-9 shrink-0 place-items-center rounded-full",
                  TONE_BG[s.tone],
                )}
              >
                <span className={cn("size-3.5 rounded-full", TONE_DOT[s.tone], s.status === "held" && "ring-4 ring-primary/30")} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium">{s.name}</span>
                <span className={cn("block text-[13px] font-medium", TONE_TEXT[s.tone])}>{s.label}</span>
              </span>
              <span className="tabular shrink-0 text-[13px] text-muted-foreground">{formatDistance(s.distM)}</span>
            </li>
          ))}
        </ol>
      )}
      <p className="border-t border-border px-5 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
        Where a signal is not held for you, its colour is approximate. Slow down and check the junction before crossing.
      </p>
    </Panel>
  );
}
