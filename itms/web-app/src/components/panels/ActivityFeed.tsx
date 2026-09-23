import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Ambulance,
  Flame,
  Shield,
  Route as RouteIcon,
} from "lucide-react";
import { useIncidentStore } from "@/store/incidentStore";
import { isTerminalRequest, useEmergencyStore } from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import { edgeById } from "@/data/network";
import { ANOMALY_SEVERITY_COLOR } from "@/components/map/mapColors";
import { formatRelative } from "@/utils/format";
import { cn } from "@/utils/cn";
import type {
  Anomaly,
  EmergencyRequest,
  EmergencyVehicleKind,
} from "@/types";

const KIND_ICON: Record<EmergencyVehicleKind, typeof Ambulance> = {
  ambulance: Ambulance,
  fire_truck: Flame,
  police: Shield,
};

type Row =
  | { type: "anomaly"; at: number; item: Anomaly }
  | { type: "emergency"; at: number; item: EmergencyRequest };

/**
 * Merged, time-ordered feed of anomalies and emergency requests — the Command
 * Center's "what's happening right now" rail. Clicking a row selects it and
 * pans the map (anomaly) or opens the Emergency workspace (request).
 */
export function ActivityFeed({ className }: { className?: string }) {
  const anomalies = useIncidentStore((s) => s.anomalies);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const requests = useEmergencyStore((s) => s.requests);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const focusOn = useMapStore((s) => s.focusOn);
  const navigate = useNavigate();

  const rows = useMemo<Row[]>(() => {
    const a: Row[] = anomalies.map((item) => ({
      type: "anomaly",
      at: Date.parse(item.startTime) || 0,
      item,
    }));
    const e: Row[] = requests.map((item) => ({
      type: "emergency",
      at: Date.parse(item.updatedAt) || 0,
      item,
    }));
    return [...a, ...e].sort((x, y) => y.at - x.at).slice(0, 40);
  }, [anomalies, requests]);

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <h2 className="text-sm font-semibold">Live activity</h2>
        <span className="font-mono text-[11px] text-muted-foreground">{rows.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            Nothing active. Create an anomaly or dispatch a unit from the map.
          </p>
        )}
        <ul className="divide-y divide-border/60">
          {rows.map((row) =>
            row.type === "anomaly" ? (
              <AnomalyRow
                key={`a-${row.item.id}`}
                a={row.item}
                onClick={() => {
                  selectAnomaly(row.item.id);
                  const e = edgeById.get(row.item.edgeId);
                  if (e) {
                    const mid = e.path[Math.floor(e.path.length / 2)];
                    focusOn({ longitude: mid[0], latitude: mid[1] });
                  }
                }}
              />
            ) : (
              <EmergencyRow
                key={`e-${row.item.id}`}
                r={row.item}
                onClick={() => {
                  selectRequest(row.item.id);
                  navigate("/console/emergency");
                }}
              />
            ),
          )}
        </ul>
      </div>
    </div>
  );
}

function AnomalyRow({ a, onClick }: { a: Anomaly; onClick: () => void }) {
  const terminal = a.status !== "active";
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-muted",
          terminal && "opacity-55",
        )}
      >
        <AlertTriangle
          className="mt-0.5 size-4 shrink-0"
          style={{ color: ANOMALY_SEVERITY_COLOR[a.severity] }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xs font-medium">
              {label(a.kind)} · {a.edgeId}
            </span>
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {formatRelative(a.startTime)}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            <span style={{ color: ANOMALY_SEVERITY_COLOR[a.severity] }}>{a.severity}</span>
            <span>·</span>
            <span>{a.source.replace("_", " ")}</span>
            <span>·</span>
            <span>{Math.round(a.estimatedImpact * 100)}% impact</span>
            {terminal && <span className="text-muted-foreground">· {a.status}</span>}
          </div>
        </div>
      </button>
    </li>
  );
}

function EmergencyRow({ r, onClick }: { r: EmergencyRequest; onClick: () => void }) {
  const Icon = KIND_ICON[r.vehicleKind] ?? RouteIcon;
  const terminal = isTerminalRequest(r);
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-muted",
          terminal && "opacity-55",
        )}
      >
        <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xs font-medium">
              {r.vehicleId} · {r.state.replace(/_/g, " ")}
            </span>
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {formatRelative(r.updatedAt)}
            </span>
          </div>
          <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
            {r.detail || `${r.sourceEdge} → ${r.destinationEdge}`}
            {r.etaS != null && ` · ETA ${fmtEta(r.etaS)}`}
          </div>
        </div>
      </button>
    </li>
  );
}

function label(kind: string): string {
  return kind.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function fmtEta(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${Math.round(s % 60)
    .toString()
    .padStart(2, "0")}`;
}
