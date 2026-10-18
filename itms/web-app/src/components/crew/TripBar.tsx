import { List, Volume2, VolumeX } from "lucide-react";
import { Meter } from "@/components/console/kit";
import { mmss } from "@/components/console/words";
import { RerouteButton } from "@/components/crew/RerouteButton";
import { canSpeak } from "@/crew/useGuidanceVoice";
import { formatDistance } from "@/crew/plan";
import type { Mission } from "@/crew/useMission";
import { cn } from "@/utils/cn";

const clock = (etaS: number | null) =>
  etaS == null ? "–" : new Date(Date.now() + etaS * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-[12px] font-medium text-muted-foreground">{label}</p>
      <p className={cn("tabular truncate leading-tight", strong ? "text-[28px] font-semibold tracking-[-0.02em]" : "text-xl font-medium")}>{value}</p>
    </div>
  );
}

/** Time, distance and speed at a glance, with the few controls a crew needs. */
export function TripBar({
  mission,
  unitName,
  voice,
  onVoice,
  onDirections,
  className,
}: {
  mission: Mission;
  unitName: string;
  voice: boolean;
  onVoice: () => void;
  onDirections: () => void;
  className?: string;
}) {
  const total = mission.plan?.totalM ?? mission.request.route?.totalDistanceM ?? 0;
  const progress = total > 0 ? 1 - mission.remainingM / total : 0;
  const speedKmh = Math.round((mission.request.live?.speedMps ?? 0) * 3.6);
  const ctl =
    "grid size-11 place-items-center rounded-full bg-muted/70 transition-colors duration-150 hover:bg-muted active:scale-95 [&_svg]:size-[18px]";

  return (
    <section aria-label="Trip progress" className={cn("pointer-events-auto rounded-[22px] bg-surface-raised p-4 shadow-elevation-3", className)}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Stat label="Arrive" value={clock(mission.etaS)} strong />
        <Stat label="Time left" value={mmss(mission.etaS)} />
        <Stat label="Distance" value={formatDistance(mission.remainingM)} />
        <Stat label="Speed" value={`${speedKmh} km/h`} />
        <div className="ml-auto flex items-center gap-2">
          <button type="button" className={ctl} aria-label="Show all directions" title="All directions" onClick={onDirections}>
            <List />
          </button>
          {canSpeak && (
            <button type="button" className={cn(ctl, voice && "bg-primary-muted text-primary")} aria-pressed={voice} aria-label={voice ? "Turn voice guidance off" : "Turn voice guidance on"} title={voice ? "Voice on" : "Voice off"} onClick={onVoice}>
              {voice ? <Volume2 /> : <VolumeX />}
            </button>
          )}
          <RerouteButton requestId={mission.request.id} unitName={unitName} />
        </div>
      </div>
      <Meter value={progress} tone="ok" className="mt-3" />
    </section>
  );
}
