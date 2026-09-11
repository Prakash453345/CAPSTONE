import { useSyncExternalStore } from "react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { ActivityFeed } from "@/components/panels/ActivityFeed";
import { CommandActionBar } from "@/components/panels/CommandActionBar";
import { StatTile } from "@/components/ui/stat-tile";
import { useSystemStore } from "@/store/systemStore";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { selectActiveRequests, useEmergencyStore } from "@/store/emergencyStore";
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

/**
 * Command Center: headline telemetry, the live corridor map, and the merged
 * anomaly / emergency activity feed — everything an operator needs at a glance
 * before drilling into a workspace.
 */
export function DashboardPage() {
  useSecondTick();
  const summary = useSystemStore((s) => s.summary);
  const lastTickAt = useTrafficStore((s) => s.lastTickAt);
  const activeAnomalies = useIncidentStore(
    (s) => s.anomalies.filter((a) => a.status === "active").length,
  );
  const activeEmergencies = useEmergencyStore((s) => selectActiveRequests(s).length);

  const congestionPct = Math.round(summary.congestion * 100);
  const stale = lastTickAt != null && Date.now() - lastTickAt > 6000;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <StatTile label="Vehicles" value={formatCount(summary.vehicleCount)} hint="on the corridor" className="w-32" />
        <StatTile
          label="Congestion"
          value={congestionPct}
          unit="%"
          tone={congestionPct > 60 ? "critical" : congestionPct > 35 ? "warn" : "ok"}
          className="w-32"
        />
        <StatTile
          label="Anomalies"
          value={activeAnomalies}
          tone={activeAnomalies > 0 ? "warn" : "ok"}
          hint="active"
          className="w-32"
        />
        <StatTile
          label="Emergencies"
          value={activeEmergencies}
          tone={activeEmergencies > 0 ? "info" : "ok"}
          hint="in progress"
          className="w-32"
        />
        <StatTile
          label="Signals"
          value={`${summary.signalsOnline}/${summary.signalsTotal}`}
          hint="under control"
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

      <CommandActionBar />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="relative min-h-0 flex-1">
          <TrafficMap />
        </div>
        <aside className="min-h-0 shrink-0 border-t border-border lg:w-80 lg:border-l lg:border-t-0">
          <ActivityFeed className="h-64 lg:h-full" />
        </aside>
      </div>
    </div>
  );
}
