import { TrafficMap } from "@/components/map/TrafficMap";
import {
  RoadConditions,
  SignalHealth,
} from "@/components/panels/NetworkPanels";
import { DataFreshness } from "@/components/layout/DataFreshness";

export function TrafficPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <div>
          <span className="eyebrow">NETWORK EXPLORER</span>
          <h1 className="mt-1 text-lg font-semibold tracking-tight">
            Every road. One clear picture.
          </h1>
        </div>
        <DataFreshness />
      </div>
      <div className="operational-workspace flex min-h-0 flex-1">
        <aside className="traffic-roster">
          <RoadConditions />
          <SignalHealth />
        </aside>
        <div className="relative min-h-0 flex-1">
          <TrafficMap />
        </div>
      </div>
    </div>
  );
}
