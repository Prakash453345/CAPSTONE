import { useState } from "react";
import { IncidentInbox } from "@/components/panels/IncidentInbox";
import { AlertTriangle, Columns2, Loader2, MapPin, X } from "lucide-react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";
import { edgeById } from "@/data/network";
import { ANOMALY_SEVERITY_COLOR } from "@/components/map/mapColors";
import { formatRelative } from "@/utils/format";
import { cn } from "@/utils/cn";
import { CommandError, postCommand } from "@/services/traffic/commands";
import type { Anomaly } from "@/types";

/**
 * Anomaly Detection workspace: the roster of anomalies on the network (operator
 * and, later, model / vision sources), with severity, impact, source and
 * status. Selecting one drives the shared `selectedAnomalyId` and pans the map.
 */
export function AnomaliesPage() {
  const anomalies = useIncidentStore((s) => s.anomalies);
  const selectedId = useIncidentStore((s) => s.selectedAnomalyId);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const focusOn = useMapStore((s) => s.focusOn);
  const setViewMode = useSystemStore((s) => s.setViewMode);

  const active = anomalies.filter((a) => a.status === "active");
  const sorted = [...anomalies].sort((a, b) => {
    if ((a.status === "active") !== (b.status === "active")) {
      return a.status === "active" ? -1 : 1;
    }
    return (Date.parse(b.startTime) || 0) - (Date.parse(a.startTime) || 0);
  });

  const focusEdge = (edgeId: string, zoom?: number) => {
    const e = edgeById.get(edgeId);
    if (e) {
      const mid = e.path[Math.floor(e.path.length / 2)];
      focusOn({ longitude: mid[0], latitude: mid[1] }, zoom);
    }
  };

  const select = (a: Anomaly) => {
    selectAnomaly(a.id === selectedId ? null : a.id);
    focusEdge(a.edgeId);
  };

  // Phase 8 cross-focus: jump into Split View with the Traffic Management
  // pane centred on this anomaly's location. Both panes' `TrafficMap`s read
  // the same `mapStore.focus`, so this `focusOn` is all that's needed to
  // move the traffic pane too -- no anomaly<->traffic-specific plumbing.
  const viewTrafficHere = (a: Anomaly) => {
    focusEdge(a.edgeId, 16);
    setViewMode("split");
  };

  return (
    <div className="operational-workspace flex h-full">
      <aside className="workspace-roster flex w-[340px] shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Anomalies</h2>
          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
            {active.length} active · {anomalies.length} total
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <IncidentInbox />
          {anomalies.length === 0 && (
            <p className="px-2 py-8 text-center text-xs text-muted-foreground">
              No anomalies on the network. Use{" "}
              <span className="text-foreground">Create anomaly</span> on the map to add one.
            </p>
          )}
          <ul className="space-y-1">
            {sorted.map((a) => {
              const terminal = a.status !== "active";
              const isSel = a.id === selectedId;
              return (
                <li
                  key={a.id}
                  className={cn(
                    "rounded-md border transition-colors",
                    isSel
                      ? "border-primary/70 bg-primary/10"
                      : "border-transparent hover:border-border hover:bg-muted",
                    terminal && "opacity-55",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => select(a)}
                    className="w-full px-2.5 py-2 text-left"
                  >
                    <div className="flex items-center gap-2">
                      <AlertTriangle
                        className="size-4 shrink-0"
                        style={{ color: ANOMALY_SEVERITY_COLOR[a.severity] }}
                      />
                      <span className="truncate text-xs font-medium">
                        {label(a.kind)}
                      </span>
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-muted-foreground">
                        {formatRelative(a.startTime)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <span style={{ color: ANOMALY_SEVERITY_COLOR[a.severity] }}>
                        {a.severity}
                      </span>
                      <span>·</span>
                      <span>{a.source.replace(/_/g, " ")}</span>
                      {terminal && <span>· {a.status}</span>}
                    </div>
                    <div className="mt-1 flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
                      <MapPin className="size-3" />
                      {a.edgeId}
                      <span className="ml-auto">{Math.round(a.estimatedImpact * 100)}% impact</span>
                    </div>
                    {a.detail && (
                      <p className="mt-1 truncate text-[11px] text-muted-foreground">{a.detail}</p>
                    )}
                  </button>
                  {isSel && (
                    <div className="border-t border-border/60 px-2.5 py-1.5">
                      <button
                        type="button"
                        onClick={() => viewTrafficHere(a)}
                        className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground"
                      >
                        <Columns2 className="size-3" />
                        View traffic in this area
                      </button>
                    </div>
                  )}
                  {a.status === "active" && (
                    <div className="border-t border-border/60 px-2.5 py-1.5">
                      <ClearAnomalyControl anomaly={a} />
                    </div>
                  )}
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

function label(kind: string): string {
  return kind.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/**
 * Manual clear for an active anomaly (Phase 7) — the operator picks whether
 * the disruption genuinely ended (`RESOLVED`) or it was reported in error
 * (`CANCELLED`), matching `AnomalyClearRequested`'s own two meanings. Always
 * a two-step confirm; a failed POST shows inline (the request never left the
 * browser). A *successful* clear doesn't need its own success toast here —
 * once it round-trips through `AnomalyUpdated`, the notification layer
 * (Phase 5) already surfaces "Anomaly cleared" and the row updates itself.
 */
function ClearAnomalyControl({ anomaly }: { anomaly: Anomaly }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<null | "RESOLVED" | "CANCELLED">(null);
  const [error, setError] = useState<string | null>(null);

  const clear = async (resolution: "RESOLVED" | "CANCELLED") => {
    setBusy(resolution);
    setError(null);
    try {
      await postCommand({
        event_type: "AnomalyClearRequested",
        payload: {
          anomaly_id: anomaly.id,
          resolution,
          reason: resolution === "CANCELLED" ? "reported in error" : "",
          requested_at: Date.now(),
        },
      });
      setConfirming(false);
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Backend unreachable — is the live simulation running?"
            : err.detail
          : "Could not clear the anomaly.",
      );
    } finally {
      setBusy(null);
    }
  };

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-[11px] text-muted-foreground hover:text-foreground"
      >
        Clear anomaly…
      </button>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">Clear this anomaly?</span>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          disabled={busy != null}
          aria-label="Keep active"
          className="grid size-4 place-items-center rounded text-muted-foreground hover:text-foreground"
        >
          <X className="size-3" />
        </button>
      </div>
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => clear("RESOLVED")}
          disabled={busy != null}
          className="flex flex-1 items-center justify-center gap-1 rounded-md bg-status-ok-muted px-2 py-1 text-[11px] font-medium text-status-ok transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {busy === "RESOLVED" && <Loader2 className="size-3 animate-spin" />}
          Resolved
        </button>
        <button
          type="button"
          onClick={() => clear("CANCELLED")}
          disabled={busy != null}
          className="flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-60"
        >
          {busy === "CANCELLED" && <Loader2 className="size-3 animate-spin" />}
          Reported in error
        </button>
      </div>
      {error && <p className="text-[11px] text-status-critical">{error}</p>}
    </div>
  );
}
