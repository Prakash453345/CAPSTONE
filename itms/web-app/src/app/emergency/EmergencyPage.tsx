import { Ambulance, Flame, Shield, ChevronRight } from "lucide-react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { cn } from "@/utils/cn";
import {
  useEmergencyStore,
  selectActiveRequests,
  selectSelectedRequest,
  selectVisibleRequests,
} from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import { edgeById } from "@/data/network";
import type { EmergencyRequest, EmergencyVehicleKind } from "@/types";

const KIND_ICON: Record<EmergencyVehicleKind, typeof Ambulance> = {
  ambulance: Ambulance,
  fire_truck: Flame,
  police: Shield,
};

const STATE_LABEL: Record<EmergencyRequest["state"], [string, string]> = {
  created: ["Created", "text-muted-foreground"],
  routing: ["Routing", "text-primary"],
  route_ready: ["Route ready", "text-[#46c46a]"],
  green_corridor_active: ["Corridor active", "text-[#46c46a]"],
  in_transit: ["In transit", "text-primary"],
  completed: ["Completed", "text-muted-foreground"],
  cancelled: ["Cancelled", "text-[#f0a6a6]"],
};

/**
 * Emergency Response workspace: the live request roster on the left, the map
 * (with the emergency route + unit layers on) on the right. Every active
 * mission renders on the map at once; selecting one here (or on the map) sets
 * `selectedRequestId` — the same field `EmergencyRouteLayer` /
 * `EmergencyVehicleLayer` / `EmergencyPanel` all read — which emphasises that
 * mission and pans the map to it without hiding any of the others.
 */
export function EmergencyPage() {
  const requests = useEmergencyStore(selectVisibleRequests);
  const selected = useEmergencyStore(selectSelectedRequest);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const focusOn = useMapStore((s) => s.focusOn);
  const active = useEmergencyStore(selectActiveRequests);

  // Selecting a mission from the roster brings the map to it — its live
  // position if it's already moving, else where it will depart from. This
  // never hides any other active mission; every one of them keeps rendering.
  const selectAndFocus = (r: EmergencyRequest, isSel: boolean) => {
    selectRequest(isSel ? null : r.id);
    if (isSel) return;
    if (r.live?.lat != null && r.live?.lon != null) {
      focusOn({ latitude: r.live.lat, longitude: r.live.lon }, 16);
    } else {
      const e = edgeById.get(r.sourceEdge);
      if (e) {
        const mid = e.path[Math.floor(e.path.length / 2)];
        focusOn({ longitude: mid[0], latitude: mid[1] }, 16);
      }
    }
  };

  return (
    <div className="flex h-full">
      <aside className="flex w-[300px] shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Emergency requests</h2>
          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
            {active.length} active · {requests.length} total
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {requests.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              No emergency requests yet. Start one from the map with{" "}
              <span className="text-foreground">Emergency response</span>.
            </p>
          )}

          <ul className="space-y-1">
            {requests.map((r) => {
              const Icon = KIND_ICON[r.vehicleKind];
              const [label, tone] = STATE_LABEL[r.state];
              const isSel = selected?.id === r.id;
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => selectAndFocus(r, isSel)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors",
                      isSel
                        ? "border-primary/70 bg-primary/10"
                        : "border-transparent hover:border-border hover:bg-muted",
                    )}
                  >
                    <Icon className="size-4 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium">
                          {r.vehicleId}
                        </span>
                        <span
                          className={cn(
                            "font-mono text-[10px] uppercase tracking-wide",
                            tone,
                          )}
                        >
                          {label}
                        </span>
                      </div>
                      <div className="truncate font-mono text-[10px] text-muted-foreground">
                        {r.sourceEdge} → {r.destinationEdge}
                        {r.etaS != null && ` · ETA ${fmtDuration(r.etaS)}`}
                      </div>
                      {r.live && r.state === "in_transit" && (
                        <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-[width] duration-700"
                            style={{ width: `${Math.round(r.live.routeProgress * 100)}%` }}
                          />
                        </div>
                      )}
                    </div>
                    <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </aside>

      <div className="relative min-h-0 flex-1">
        <TrafficMap />
      </div>
    </div>
  );
}

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
