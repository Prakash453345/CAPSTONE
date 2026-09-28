import { useState } from "react";
import {
  Ambulance,
  AlertTriangle,
  ChevronRight,
  X,
  Loader2,
  MapPin,
  Flag,
  RefreshCw,
  Route as RouteIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SimModeNotice } from "@/components/map/SimModeNotice";
import { cn } from "@/utils/cn";
import { CommandError, postCommand } from "@/services/traffic/commands";
import {
  PRESET_UNITS,
  corridorHoldSeconds,
  isTerminalRequest,
  nextCorridorReservation,
  orderedReservations,
  requestRoutes,
  rerouteCount,
  useEmergencyStore,
  selectSelectedRequest,
  type PresetUnit,
} from "@/store/emergencyStore";
import { useMapStore, type MapInteractionMode } from "@/store/mapStore";
import { edgeById, roadEdges, shortJunctionName } from "@/data/network";
import type {
  EmergencyRequest,
  EmergencyRouteView,
  EmergencyVehicleLive,
  GreenCorridorView,
} from "@/types";

const WEIGHT_LABEL: Record<string, string> = {
  travel_time_weight: "travel time",
  congestion_weight: "congestion",
  anomaly_weight: "anomaly",
  signal_delay_weight: "signal delay",
  disruption_weight: "disruption",
  reliability_weight: "reliability",
};

const KIND_EVENT: Record<PresetUnit["kind"], string> = {
  ambulance: "AMBULANCE",
  fire_truck: "FIRE_TRUCK",
  police: "POLICE",
};

/**
 * Emergency Response flow on the map: pick a unit, set source + destination by
 * clicking the map, calculate a route, then review it before activating a
 * green corridor. Once a request exists the panel switches to the route
 * preview (fed by the live `emergency.request-updated` stream).
 */
export function EmergencyPanel() {
  const draft = useEmergencyStore((s) => s.draft);
  const startDraft = useEmergencyStore((s) => s.startDraft);
  const selected = useEmergencyStore(selectSelectedRequest);

  if (selected && !draft) return <RoutePreview request={selected} />;
  if (draft) return <DispatchDraftPanel />;

  return (
    <button
      type="button"
      onClick={() => startDraft(PRESET_UNITS[0])}
      className="pointer-events-auto flex items-center gap-1.5 rounded-lg border border-border bg-surface/90 px-2.5 py-1.5 text-xs font-medium text-muted-foreground shadow-panel backdrop-blur-sm transition-colors hover:text-foreground"
    >
      <Ambulance className="size-3.5" />
      Emergency response
    </button>
  );
}

function DispatchDraftPanel() {
  const draft = useEmergencyStore((s) => s.draft)!;
  const setDraftUnit = useEmergencyStore((s) => s.setDraftUnit);
  const clearDraft = useEmergencyStore((s) => s.clearDraft);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const interactionMode = useMapStore((s) => s.interactionMode);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = draft.source && draft.destination;

  const pick = (which: MapInteractionMode) =>
    setInteractionMode(interactionMode === which ? "idle" : which);

  const cancel = () => {
    setInteractionMode("idle");
    clearDraft();
  };

  const calculate = async () => {
    if (!draft.source || !draft.destination) return;
    setBusy(true);
    setError(null);
    const requestId = crypto.randomUUID();
    try {
      await postCommand({
        event_type: "EmergencyRequestCreated",
        payload: {
          request_id: requestId,
          vehicle_id: draft.unit.id,
          vehicle_kind: KIND_EVENT[draft.unit.kind],
          source_edge: draft.source.edgeId,
          destination_edge: draft.destination.edgeId,
          priority: 1,
          requested_at: Date.now(),
        },
      });
      selectRequest(requestId);
      setInteractionMode("idle");
      clearDraft();
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Backend unreachable — is the live simulation running?"
            : err.detail
          : "Could not calculate the route.",
      );
      setBusy(false);
    }
  };

  return (
    <div className="pointer-events-auto w-[300px] rounded-lg border border-border bg-surface-raised shadow-panel-lg">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Ambulance className="size-4 text-primary" />
          <span className="text-sm font-semibold">Emergency response</span>
        </div>
        <button
          type="button"
          aria-label="Cancel"
          onClick={cancel}
          className="grid size-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-3.5"
        >
          <X />
        </button>
      </div>

      <div className="space-y-3 p-3">
        <SimModeNotice />

        <div>
          <Label>Unit</Label>
          <div className="grid grid-cols-2 gap-1">
            {PRESET_UNITS.map((u) => (
              <button
                key={u.id}
                type="button"
                onClick={() => setDraftUnit(u)}
                className={cn(
                  "rounded-md border px-2 py-1.5 text-left text-xs transition-colors",
                  draft.unit.id === u.id
                    ? "border-primary/70 bg-primary/15 text-foreground"
                    : "border-border bg-surface text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="block font-medium">{u.callSign}</span>
                <span className="block text-[10px] uppercase tracking-wide opacity-70">
                  {u.kind.replace("_", " ")}
                </span>
              </button>
            ))}
          </div>
        </div>

        <PointRow
          icon={<MapPin className="size-3.5" />}
          label="Source"
          which="source"
          point={draft.source}
          picking={interactionMode === "pick-source"}
          onPick={() => pick("pick-source")}
        />
        <PointRow
          icon={<Flag className="size-3.5" />}
          label="Destination"
          which="destination"
          point={draft.destination}
          picking={interactionMode === "pick-destination"}
          onPick={() => pick("pick-destination")}
        />

        {error && (
          <p className="rounded-md bg-[color-mix(in_srgb,#e5484d_14%,transparent)] px-2.5 py-1.5 text-[11px] text-[#f0a6a6]">
            {error}
          </p>
        )}

        <Button className="w-full" onClick={calculate} disabled={!ready || busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <RouteIcon className="size-4" />}
          {busy ? "Calculating…" : "Calculate route"}
        </Button>
      </div>
    </div>
  );
}

type BusyKind = "corridor" | "cancel" | "recalc";

function RoutePreview({ request }: { request: EmergencyRequest }) {
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const archiveRequest = useEmergencyStore((s) => s.archiveRequest);
  const previewRank = useEmergencyStore((s) => s.previewRank);
  const setPreviewRank = useEmergencyStore((s) => s.setPreviewRank);
  const [busy, setBusy] = useState<null | BusyKind>(null);
  const [error, setError] = useState<string | null>(null);

  const routes = requestRoutes(request);
  const active = routes[0] ?? null; // the one the backend dispatches
  const previewed = routes[previewRank] ?? active;
  const isPreviewingAlt = previewed != null && previewed !== active;
  const reroutable = request.state === "route_ready" || request.state === "in_transit";
  const terminal = isTerminalRequest(request);

  const send = async (action: string, kind: BusyKind) => {
    setBusy(kind);
    setError(null);
    try {
      await postCommand({
        event_type: "EmergencyCommand",
        payload: { request_id: request.id, action, requested_at: Date.now() },
      });
      if (kind === "cancel") selectRequest(null);
    } catch (err) {
      setError(err instanceof CommandError ? err.detail : "Command failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="pointer-events-auto w-[308px] rounded-lg border border-border bg-surface-raised shadow-panel-lg">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <RouteIcon className="size-4 text-primary" />
          <span className="text-sm font-semibold">Emergency route</span>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={() => selectRequest(null)}
          className="grid size-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-3.5"
        >
          <X />
        </button>
      </div>

      <div className="max-h-[calc(100vh-9rem)] space-y-2.5 overflow-y-auto p-3">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">{request.vehicleId}</span>
          <StatePill state={request.state} />
        </div>

        {terminal ? (
          <MissionSummary
            request={request}
            onDismiss={() => {
              archiveRequest(request.id);
              selectRequest(null);
            }}
          />
        ) : (
          <>
            {request.state === "routing" && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> calculating route…
              </p>
            )}

            {request.detail && /reroute/i.test(request.detail) && (
              <p className="flex items-start gap-1.5 rounded-md border border-[#f5b83d]/40 bg-[color-mix(in_srgb,#f5b83d_10%,transparent)] px-2.5 py-1.5 text-[11px] text-[#f5b83d]">
                <RefreshCw className="mt-px size-3 shrink-0" />
                {request.detail.replace(/^auto-reroute — /, "Auto-rerouted: ")}
              </p>
            )}

            {previewed && (
              <>
                {previewed.forcedThrough.length > 0 && (
                  <p className="flex items-start gap-1.5 rounded-md border border-[#e5484d]/40 bg-[color-mix(in_srgb,#e5484d_10%,transparent)] px-2.5 py-1.5 text-[11px] text-[#f0a6a6]">
                    <AlertTriangle className="mt-px size-3 shrink-0" />
                    <span>
                      This is the only route available, and it crosses{" "}
                      {previewed.forcedThrough.length} blocked segment
                      {previewed.forcedThrough.length > 1 ? "s" : ""}. The vehicle can still
                      get through, but expect serious delays — proceed with caution.
                    </span>
                  </p>
                )}

                {routes.length > 1 && (
                  <RouteTabs
                    routes={routes}
                    previewRank={previewRank}
                    onPick={setPreviewRank}
                  />
                )}

                <div className="grid grid-cols-2 gap-1.5">
                  <Metric label="ETA" value={fmtDuration(previewed.etaS)} />
                  <Metric
                    label="Distance"
                    value={`${(previewed.totalDistanceM / 1000).toFixed(1)} km`}
                  />
                  <Metric label="Intersections" value={String(previewed.nIntersections)} />
                  <Metric label="Signals" value={String(previewed.signalisedIntersections.length)} />
                  <Metric
                    label="Signal delay"
                    value={`${Math.round(previewed.cost.signalDelayS)} s`}
                  />
                  <Metric
                    label="Congested"
                    value={`${previewed.congestedSegments.length} seg`}
                    tone={previewed.congestedSegments.length ? "bad" : undefined}
                  />
                </div>

                <div className="grid grid-cols-2 gap-1.5">
                  <div className="flex items-center justify-between rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs">
                    <span className="text-muted-foreground">Score</span>
                    <span className="font-mono font-semibold">
                      {previewed.cost.score.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs">
                    <span className="text-muted-foreground">Reliability</span>
                    <span
                      className={cn(
                        "font-mono font-semibold",
                        previewed.reliable ? "text-[#46c46a]" : "text-[#f5b83d]",
                      )}
                    >
                      {previewed.reliable ? "OK" : "low"}
                    </span>
                  </div>
                </div>

                <CostBar route={previewed} />

                {previewed.anomalousSegmentsAvoided.length > 0 && (
                  <p className="flex items-center gap-1 text-[11px] text-[#46c46a]">
                    <span className="size-1.5 rounded-full bg-[#46c46a]" />
                    steered around {previewed.anomalousSegmentsAvoided.length} anomalous segment
                    {previewed.anomalousSegmentsAvoided.length > 1 ? "s" : ""}
                  </p>
                )}
                {previewed.congestedSegments.length > 0 && (
                  <p className="flex items-center gap-1 text-[11px] text-[#f5b83d]">
                    <span className="size-1.5 rounded-full bg-[#f5b83d]" />
                    {previewed.congestedSegments.length} congested segment
                    {previewed.congestedSegments.length > 1 ? "s" : ""} on this route
                  </p>
                )}

                <WhyThisRoute route={previewed} />

                {isPreviewingAlt && (
                  <p className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-[11px] text-muted-foreground">
                    Previewing an alternative. The{" "}
                    <span className="text-foreground">recommended</span> route is the one
                    dispatched — use <span className="text-foreground">Recalculate</span> to
                    re-plan from current conditions.
                  </p>
                )}
              </>
            )}

            {error && (
              <p className="rounded-md bg-[color-mix(in_srgb,#e5484d_14%,transparent)] px-2.5 py-1.5 text-[11px] text-[#f0a6a6]">
                {error}
              </p>
            )}

            {request.corridor && request.state !== "route_ready" && (
              <CorridorStatus corridor={request.corridor} live={request.live} />
            )}

            {reroutable && (
              <button
                type="button"
                onClick={() => send("RECALCULATE", "recalc")}
                disabled={busy != null}
                className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <RefreshCw className={cn("size-3.5", busy === "recalc" && "animate-spin")} />
                {busy === "recalc" ? "Recalculating…" : "Recalculate route"}
              </button>
            )}

            {active && request.state === "route_ready" && (
              <Button
                className="w-full"
                onClick={() => send("ACTIVATE_CORRIDOR", "corridor")}
                disabled={busy != null}
                title="Coordinate signals along the route ahead of the vehicle"
              >
                {busy === "corridor" ? <Loader2 className="size-4 animate-spin" /> : null}
                Activate green corridor
              </Button>
            )}
            <button
              type="button"
              onClick={() => send("CANCEL", "cancel")}
              disabled={busy != null}
              className="w-full rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              {busy === "cancel" ? "Cancelling…" : "Cancel request"}
            </button>
          </>
        )}

        <Timeline entries={request.timeline} />
      </div>
    </div>
  );
}

/** Shown in place of the routing/dispatch UI once a request reaches a
 *  terminal state — a snapshot of the mission plus an explicit dismiss, since
 *  Phase 6 stopped the provider from silently pruning completed requests a
 *  few seconds after arrival. */
function MissionSummary({
  request,
  onDismiss,
}: {
  request: EmergencyRequest;
  onDismiss: () => void;
}) {
  const route = request.route;
  const reroutes = rerouteCount(request);
  const source = edgeById.get(request.sourceEdge)?.name ?? request.sourceEdge;
  const destination = edgeById.get(request.destinationEdge)?.name ?? request.destinationEdge;
  const cancelled = request.state === "cancelled";

  return (
    <div className="space-y-2.5">
      <div
        className={cn(
          "rounded-md border px-2.5 py-2",
          cancelled
            ? "border-[#e5484d]/40 bg-[color-mix(in_srgb,#e5484d_8%,transparent)]"
            : "border-[#46c46a]/40 bg-[color-mix(in_srgb,#46c46a_8%,transparent)]",
        )}
      >
        <p className={cn("text-xs font-semibold", cancelled ? "text-[#f0a6a6]" : "text-[#46c46a]")}>
          {cancelled ? "Mission cancelled" : "Mission complete"}
        </p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          {cancelled
            ? request.detail || "The request was cancelled before arrival."
            : `Arrived ${relTime(new Date(request.updatedAt).getTime())}`}
        </p>
      </div>

      <div className="space-y-1 rounded-md border border-border bg-surface px-2.5 py-2 text-[11px]">
        <SummaryRow label="Vehicle" value={request.vehicleId} />
        <SummaryRow label="From" value={source} />
        <SummaryRow label="To" value={destination} />
        <SummaryRow
          label={cancelled ? "Cancelled at" : "Arrived at"}
          value={new Date(request.updatedAt).toLocaleTimeString()}
        />
      </div>

      {route && (
        <div className="grid grid-cols-2 gap-1.5">
          <Metric label="Distance" value={`${(route.totalDistanceM / 1000).toFixed(1)} km`} />
          <Metric label="Planned travel time" value={fmtDuration(route.totalTravelTimeS)} />
          <Metric label="Reroutes" value={String(reroutes)} tone={reroutes ? "bad" : undefined} />
          <Metric
            label="Corridor"
            value={request.corridor ? CORRIDOR_STATUS_META[request.corridor.status].label : "None"}
          />
        </div>
      )}

      <button
        type="button"
        onClick={onDismiss}
        className="w-full rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        Dismiss
      </button>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium text-foreground">{value}</span>
    </div>
  );
}

function RouteTabs({
  routes,
  previewRank,
  onPick,
}: {
  routes: EmergencyRouteView[];
  previewRank: number;
  onPick: (rank: number) => void;
}) {
  return (
    <div className="flex gap-1">
      {routes.map((rt, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onPick(i)}
          className={cn(
            "flex-1 rounded-md border px-1.5 py-1 text-center text-[10px] leading-tight transition-colors",
            i === previewRank
              ? "border-primary/70 bg-primary/15 text-foreground"
              : "border-border bg-surface text-muted-foreground hover:text-foreground",
          )}
          title={`${i === 0 ? "Recommended" : `Alternative ${i}`} · ${fmtDuration(rt.etaS)} · score ${rt.cost.score.toFixed(1)}`}
        >
          <span className="block font-medium">{i === 0 ? "Recommended" : `Alt ${i}`}</span>
          <span className="block font-mono opacity-70">{fmtDuration(rt.etaS)}</span>
        </button>
      ))}
    </div>
  );
}

function WhyThisRoute({ route }: { route: EmergencyRouteView }) {
  const [open, setOpen] = useState(false);
  const parts: Array<[string, number]> = [
    ["travel time", route.cost.travelTimeS],
    ["congestion", route.cost.congestion],
    ["anomaly", route.cost.anomaly],
    ["signal delay", route.cost.signalDelayS],
    ["disruption", route.cost.disruption],
    ["reliability", route.cost.reliability],
  ];
  const weights = Object.entries(route.weightsUsed).filter(([k]) => k in WEIGHT_LABEL);
  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
      >
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
        Why this route?
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-2.5 py-2">
          <div>
            <Label>Weighted cost terms</Label>
            <ul className="space-y-0.5">
              {parts.map(([name, v]) => (
                <li key={name} className="flex justify-between text-[11px]">
                  <span className="text-muted-foreground">{name}</span>
                  <span className="font-mono">{v.toFixed(2)}</span>
                </li>
              ))}
              <li className="flex justify-between border-t border-border pt-0.5 text-[11px] font-medium">
                <span>total score</span>
                <span className="font-mono">{route.cost.score.toFixed(2)}</span>
              </li>
            </ul>
          </div>
          {weights.length > 0 && (
            <div>
              <Label>Cost weights in effect</Label>
              <div className="flex flex-wrap gap-1">
                {weights.map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                    title={WEIGHT_LABEL[k]}
                  >
                    {WEIGHT_LABEL[k]} {Number(v).toFixed(2)}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] text-muted-foreground">
            Standard weighted shortest path; the score is the sum of the normalised terms
            above. Lower is better.
          </p>
        </div>
      )}
    </div>
  );
}

function Timeline({ entries }: { entries: EmergencyRequest["timeline"] }) {
  const [open, setOpen] = useState(false);
  if (!entries || entries.length === 0) return null;
  const shown = open ? entries : entries.slice(-3);
  return (
    <div className="border-t border-border pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="mb-1.5 flex w-full items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
      >
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
        History · {entries.length}
      </button>
      <ol className="space-y-1.5">
        {shown.map((t, i) => (
          <li key={`${t.atMs}-${i}`} className="flex gap-2 text-[11px]">
            <span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary/70" />
            <div className="min-w-0">
              <span className="font-medium">{t.state.replace(/_/g, " ")}</span>
              <span className="ml-1.5 text-muted-foreground">{relTime(t.atMs)}</span>
              {t.detail && (
                <p className="truncate text-muted-foreground">{t.detail}</p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function relTime(ms: number): string {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
}

const CORRIDOR_STATUS_META: Record<
  GreenCorridorView["status"],
  { label: string; dot: string; border: string; bg: string; text: string; pulse: boolean }
> = {
  proposed: {
    label: "Proposed", pulse: false,
    dot: "bg-[#8a94a6]", border: "border-[#8a94a6]/40",
    bg: "bg-[color-mix(in_srgb,#8a94a6_8%,transparent)]", text: "text-[#8a94a6]",
  },
  active: {
    label: "Active", pulse: true,
    dot: "bg-[#46c46a]", border: "border-[#46c46a]/40",
    bg: "bg-[color-mix(in_srgb,#46c46a_8%,transparent)]", text: "text-[#46c46a]",
  },
  restoring: {
    label: "Restoring", pulse: true,
    dot: "bg-[#f5b83d]", border: "border-[#f5b83d]/40",
    bg: "bg-[color-mix(in_srgb,#f5b83d_8%,transparent)]", text: "text-[#f5b83d]",
  },
  completed: {
    label: "Completed", pulse: false,
    dot: "bg-[#8a94a6]", border: "border-[#8a94a6]/40",
    bg: "bg-[color-mix(in_srgb,#8a94a6_8%,transparent)]", text: "text-[#8a94a6]",
  },
  cancelled: {
    label: "Cancelled", pulse: false,
    dot: "bg-[#e5484d]", border: "border-[#e5484d]/40",
    bg: "bg-[color-mix(in_srgb,#e5484d_8%,transparent)]", text: "text-[#e5484d]",
  },
};

function CorridorStatus({
  corridor,
  live,
}: {
  corridor: GreenCorridorView;
  live?: EmergencyVehicleLive;
}) {
  const passed = new Set(corridor.passedIntersections);
  const ordered = orderedReservations(corridor);
  const total = ordered.length;
  const done = ordered.filter((r) => passed.has(r.intersectionId)).length;
  const next = nextCorridorReservation(corridor);
  const progressPct = live ? Math.round(live.routeProgress * 100) : 0;
  const meta = CORRIDOR_STATUS_META[corridor.status];

  return (
    <div className={cn("space-y-2 rounded-md border p-2.5", meta.border, meta.bg)}>
      <div className="flex items-center justify-between">
        <span className={cn("flex items-center gap-1.5 text-xs font-medium", meta.text)}>
          <span className="relative flex size-2">
            {meta.pulse && (
              <span
                className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", meta.dot)}
              />
            )}
            <span className={cn("relative inline-flex size-2 rounded-full", meta.dot)} />
          </span>
          Green corridor · {meta.label}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {done}/{total} cleared
        </span>
      </div>

      {next && (
        <div className="flex items-center justify-between rounded-md border border-border bg-surface px-2 py-1 text-[11px]">
          <span className="text-muted-foreground">Next junction</span>
          <span className="truncate font-mono font-medium text-foreground">
            {shortJunctionName(next.intersectionId)} · ~{corridorHoldSeconds(next)}s hold
          </span>
        </div>
      )}

      <div className="flex flex-wrap gap-1">
        {ordered.map((r) => {
          const isPassed = passed.has(r.intersectionId);
          const isNext = next?.intersectionId === r.intersectionId;
          return (
            <span
              key={r.intersectionId}
              title={`${shortJunctionName(r.intersectionId)} · ${r.movements.join(", ")} · ~${corridorHoldSeconds(r)}s hold`}
              className={cn(
                "rounded px-1.5 py-0.5 font-mono text-[10px] transition-colors",
                isPassed && "bg-muted text-muted-foreground line-through",
                !isPassed && isNext && "bg-[#46c46a]/30 text-[#46c46a] ring-1 ring-[#46c46a]",
                !isPassed && !isNext && "bg-[#46c46a]/15 text-[#46c46a]/80",
              )}
            >
              J{r.order + 1}
            </span>
          );
        })}
      </div>

      {live && (
        <div>
          <div className="mb-1 flex justify-between font-mono text-[10px] text-muted-foreground">
            <span>en route</span>
            <span>
              {progressPct}%{live.etaS != null && ` · ETA ${fmtDuration(live.etaS)}`}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-[#46c46a] transition-[width] duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ---- bits -----------------------------------------------------------------

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  );
}

function PointRow({
  icon,
  label,
  which,
  point,
  picking,
  onPick,
}: {
  icon: React.ReactNode;
  label: string;
  which: "source" | "destination";
  point: { edgeId: string; edgeName: string | null } | null;
  picking: boolean;
  onPick: () => void;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <button
        type="button"
        onClick={onPick}
        className={cn(
          "flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors",
          picking
            ? "border-primary/70 bg-primary/15 text-foreground"
            : "border-border bg-surface text-muted-foreground hover:text-foreground",
        )}
      >
        {icon}
        {point ? (
          <span className="truncate font-mono">
            {point.edgeName ?? "Edge"} · {point.edgeId}
          </span>
        ) : (
          <span>{picking ? "Click a road on the map…" : "Set on map"}</span>
        )}
      </button>
      <select aria-label={`${label} road`} className="mt-1.5 w-full rounded-md border border-border bg-surface px-2 py-2 text-[11px]" value={point?.edgeId ?? ""} onChange={(e) => {
        const edge = edgeById.get(e.target.value);
        if (!edge) return;
        useEmergencyStore.getState().setDraftPoint(which, { edgeId: edge.id, edgeName: edge.name, at: edge.path[Math.floor(edge.path.length / 2)] });
        useMapStore.getState().setInteractionMode("idle");
      }}><option value="">Or choose a road…</option>{roadEdges.map((edge) => <option key={edge.id} value={edge.id}>{edge.name ?? "Road"} · {edge.id}</option>)}</select>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-border bg-surface px-2 py-1.5">
      <div className="font-mono text-[9px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-semibold",
          tone === "good" && "text-[#46c46a]",
          tone === "bad" && "text-[#f5b83d]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function CostBar({ route }: { route: EmergencyRouteView }) {
  // Seconds and weighted penalties are different units; do not combine them
  // into a percentage bar or silently divide signal delay by an arbitrary 10.
  const parts: Array<[string, number, string]> = [
    ["Travel time", route.cost.travelTimeS, "s"],
    ["Signal delay", route.cost.signalDelayS, "s"],
    ["Congestion", route.cost.congestion, "cost"],
    ["Anomaly", route.cost.anomaly, "cost"],
    ["Disruption", route.cost.disruption, "cost"],
    ["Reliability", route.cost.reliability, "cost"],
  ];
  return <div><Label>Route factors · backend estimates</Label><dl className="grid grid-cols-2 gap-2">{parts.map(([name, value, unit]) => <div key={name} className="rounded border border-border bg-surface p-2"><dt className="text-[9px] text-muted-foreground">{name}</dt><dd className="mt-1 font-mono text-[11px]">{value.toFixed(1)} <span className="text-muted-foreground">{unit}</span></dd></div>)}</dl></div>;
}

function StatePill({ state }: { state: EmergencyRequest["state"] }) {
  const map: Record<EmergencyRequest["state"], [string, string]> = {
    created: ["Created", "text-muted-foreground"],
    routing: ["Routing", "text-primary"],
    route_ready: ["Route ready", "text-[#46c46a]"],
    green_corridor_active: ["Corridor active", "text-[#46c46a]"],
    in_transit: ["In transit", "text-primary"],
    completed: ["Completed", "text-muted-foreground"],
    cancelled: ["Cancelled", "text-[#f0a6a6]"],
  };
  const [label, cls] = map[state];
  return <span className={cn("font-mono text-[10px] uppercase tracking-wide", cls)}>{label}</span>;
}

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
