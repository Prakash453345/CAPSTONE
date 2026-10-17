import { CheckCircle2, Gauge, OctagonAlert, Siren, TriangleAlert, ZapOff } from "lucide-react";
import { Panel, PanelHeader } from "@/components/console/kit";
import { TONE_BG, TONE_TEXT } from "@/components/console/tone";
import { formatDistance } from "@/drive/plan";
import type { Hazard, HazardKind } from "@/drive/situation";
import { cn } from "@/utils/cn";

const ICONS: Record<HazardKind, typeof TriangleAlert> = {
  closure: OctagonAlert,
  disruption: TriangleAlert,
  congestion: Gauge,
  "signal-fault": ZapOff,
  unit: Siren,
};

/** What is on the road ahead that a crew should know about, nearest first. */
export function HazardsCard({ hazards, advice }: { hazards: Hazard[]; advice: string | null }) {
  return (
    <Panel aria-labelledby="hazards-title" className="pointer-events-auto">
      <PanelHeader id="hazards-title" title="On your route" subtitle={hazards.length ? `${hazards.length} to watch` : "Nothing reported"} />
      {hazards.length === 0 ? (
        <p className="flex items-center gap-2 px-5 pb-4 text-[13px] text-muted-foreground">
          <CheckCircle2 className="size-4 text-status-ok" aria-hidden />
          The road ahead is clear.
        </p>
      ) : (
        <ul className="px-3 pb-3">
          {hazards.map((h) => {
            const Icon = ICONS[h.kind];
            return (
              <li key={h.id} className="flex items-start gap-3 rounded-xl px-2 py-2.5">
                <span aria-hidden className={cn("grid size-9 shrink-0 place-items-center rounded-full", TONE_BG[h.tone], TONE_TEXT[h.tone])}>
                  <Icon className="size-[18px]" strokeWidth={1.9} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium leading-snug">{h.title}</span>
                  <span className="block text-[13px] text-muted-foreground">{h.detail}</span>
                </span>
                <span className="tabular shrink-0 pt-0.5 text-[13px] text-muted-foreground">{formatDistance(h.distM)}</span>
              </li>
            );
          })}
        </ul>
      )}
      {advice && <p className="border-t border-border px-5 py-2.5 text-[13px] text-status-warn">{advice}</p>}
    </Panel>
  );
}
