import { useMemo } from "react";
import type { Mission } from "@/crew/useMission";
import { trafficAhead, trafficAlong } from "@/crew/situation";
import { TRAFFIC_COLOR } from "@/components/map/mapColors";
import { useTrafficStore } from "@/store/trafficStore";
import { cn } from "@/utils/cn";


/**
 * The whole route as one bar coloured by live traffic, with the vehicle's
 * place on it, and a line saying what is coming: the traffic view Google Maps
 * puts under a route, so a crew sees a jam before they reach it.
 */
export function TrafficStrip({ mission, className }: { mission: Mission; className?: string }) {
  const congestion = useTrafficStore((s) => s.roadCongestion);
  const plan = mission.plan;
  const stretches = useMemo(() => (plan ? trafficAlong(plan, congestion) : []), [plan, congestion]);
  if (!plan || plan.totalM <= 0) return null;
  const total = plan.totalM;
  const at = Math.min(1, Math.max(0, mission.alongM / total));
  const line = trafficAhead(stretches, mission.alongM);
  const clear = !stretches.some((s) => s.endM > mission.alongM && s.level !== "free");

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="relative h-2.5" role="img" aria-label={line}>
        <div className="absolute inset-0 flex overflow-hidden rounded-full">
          {stretches.map((s) => (
            <span
              key={s.startM}
              style={{ width: `${((s.endM - s.startM) / total) * 100}%`, background: TRAFFIC_COLOR[s.level] }}
              className="h-full"
            />
          ))}
        </div>
        {/* already driven: washed out, like the grey line behind the vehicle on the map */}
        <div
          className="absolute inset-y-0 left-0 rounded-l-full bg-surface-raised/70"
          style={{ width: `${at * 100}%` }}
        />
        <span
          className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-surface-raised bg-primary shadow-elevation-1"
          style={{ left: `${at * 100}%` }}
        />
      </div>
      <p className={cn("text-[13px] font-medium", clear ? "text-status-ok" : "text-status-warn")}>{line}</p>
    </div>
  );
}
