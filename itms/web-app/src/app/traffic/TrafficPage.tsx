import { useSyncExternalStore } from "react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { StatTile } from "@/components/ui/stat-tile";
import { useSystemStore } from "@/store/systemStore";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { formatCount } from "@/utils/format";

function useSecondTick() {
  return useSyncExternalStore(
    (cb) => {
      const id = window.setInterval(cb, 1000);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / 1000),
  );
}

export function TrafficPage() {
  useSecondTick();
  const summary = useSystemStore((s) => s.summary);
  const lastTickAt = useTrafficStore((s) => s.lastTickAt);
  const activeIncidents = useIncidentStore(
    (s) => s.incidents.filter((i) => i.status !== "resolved").length,
  );

  const congestionPct = Math.round(summary.congestion * 100);
  const stale = lastTickAt != null && Date.now() - lastTickAt > 6000;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <StatTile
          label="Vehicles"
          value={formatCount(summary.vehicleCount)}
          hint="on the corridor"
          className="w-32"
        />
        <StatTile
          label="Congestion"
          value={congestionPct}
          unit="%"
          tone={congestionPct > 60 ? "critical" : congestionPct > 35 ? "warn" : "ok"}
          className="w-32"
        />
        <StatTile
          label="Active incidents"
          value={activeIncidents}
          tone={activeIncidents > 0 ? "warn" : "ok"}
          className="w-32"
        />
        <StatTile
          label="Signals"
          value={`${summary.signalsOnline}/${summary.signalsTotal}`}
          hint="online"
          className="w-32"
        />
        <div className="ml-auto font-mono text-[11px] text-muted-foreground">
          {stale
            ? "map data stale — reconnecting"
            : lastTickAt
              ? "live · updated 1s ago"
              : "awaiting first update…"}
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <TrafficMap />
      </div>
    </div>
  );
}
