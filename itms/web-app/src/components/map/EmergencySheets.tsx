import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ambulance,
  Check,
  ChevronRight,
  Flame,
  Hospital,
  Loader2,
  RefreshCw,
  Route as RouteIcon,
  Send,
  Shield,
  X,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { CommandError, postCommand } from "@/services/traffic/commands";
import {
  CREW_TYPES,
  corridorHoldSeconds,
  isTerminalRequest,
  nextCorridorReservation,
  orderedReservations,
  requestRoutes,
  rerouteCount,
  useEmergencyStore,
  selectSelectedRequest,
  type CrewType,
  type PendingCall,
} from "@/store/emergencyStore";
import { useCrewStore, type FleetUnit, type HospitalMission } from "@/store/crewStore";
import { useMapStore } from "@/store/mapStore";
import { roadLabel, shortJunctionName } from "@/data/network";
import { mmss, unitName } from "@/components/console/words";
import { haversineMeters } from "@/utils/geo";
import {
  Group,
  InlineError,
  PrimaryButton,
  SecondaryButton,
  SectionLabel,
  Segmented,
  Sheet,
} from "@/components/map/sheet";
import { RoadField } from "@/components/map/RoadField";
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

type Kind = CrewType["kind"];

const KIND_EVENT: Record<Kind, string> = {
  ambulance: "AMBULANCE",
  fire_truck: "FIRE_TRUCK",
  police: "POLICE",
};

const KIND_ICON: Record<Kind, React.ReactNode> = {
  ambulance: <Ambulance />,
  police: <Shield />,
  fire_truck: <Flame />,
};

const KIND_NOUN: Record<Kind, string> = {
  ambulance: "ambulance",
  police: "police unit",
  fire_truck: "fire engine",
};

function kindOf(raw: string): Kind {
  const k = raw.toLowerCase();
  return k === "police" || k === "fire_truck" ? k : "ambulance";
}

function errorText(err: unknown, fallback: string): string {
  if (err instanceof CommandError)
    return err.status === 0 ? "Can't reach the server. Is the live simulation running?" : err.detail;
  return fallback;
}

/** A unit's name as the crew roster gives it, else a readable form of its id. */
function useUnitLabel(): (unitId: string) => string {
  const fleet = useCrewStore((s) => s.fleet);
  return (unitId) => fleet.find((u) => u.unitId === unitId)?.callSign || unitName(unitId);
}

/** The sheet that is showing, if any: the request being drafted, the call
 *  while a crew is being found, or the live mission once one has accepted.
 *  Loaded on demand (see EmergencyPanel), so the map's first download does
 *  not carry it. */
export default function EmergencySheets() {
  const draft = useEmergencyStore((s) => s.draft);
  const selected = useEmergencyStore(selectSelectedRequest);
  const pendingCall = useEmergencyStore((s) => s.pendingCall);
  if (draft) return <DispatchSheet />;
  if (pendingCall) return <PendingCallSheet call={pendingCall} />;
  if (selected) return <RoutePreview request={selected} />;
  return null;
}

// ---- 1. what is needed, and where ----------------------------------------

function DispatchSheet() {
  const draft = useEmergencyStore((s) => s.draft)!;
  const setDraftUnit = useEmergencyStore((s) => s.setDraftUnit);
  const setDraftPoint = useEmergencyStore((s) => s.setDraftPoint);
  const clearDraft = useEmergencyStore((s) => s.clearDraft);
  const setPendingCall = useEmergencyStore((s) => s.setPendingCall);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const interactionMode = useMapStore((s) => s.interactionMode);
  const fleet = useCrewStore((s) => s.fleet);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind = draft.unit.kind;
  const destination = draft.destination;
  const picking = interactionMode === "pick-destination";

  const nearby = useMemo(() => rankFleet(fleet, kind, destination?.at ?? null), [fleet, kind, destination]);
  const free = nearby.filter((n) => n.status === "available").length;

  const cancel = () => {
    setInteractionMode("idle");
    clearDraft();
  };

  const send = async () => {
    if (!destination) return;
    setBusy(true);
    setError(null);
    const call: PendingCall = {
      requestId: crypto.randomUUID(),
      unit: draft.unit,
      destination,
      sentAtMs: Date.now(),
    };
    try {
      await sendCall(call);
      setPendingCall(call);
      setInteractionMode("idle");
      clearDraft();
    } catch (err) {
      setError(errorText(err, "Could not send the request."));
      setBusy(false);
    }
  };

  return (
    <Sheet
      title="Send help"
      subtitle="Nearest free crew takes the call"
      icon={<Send />}
      onClose={cancel}
      closeLabel="Cancel"
      footer={
        <PrimaryButton onClick={send} disabled={!destination || busy}>
          {busy ? <Loader2 className="animate-spin" /> : KIND_ICON[kind]}
          {busy ? "Sending…" : `Request ${KIND_NOUN[kind]}`}
        </PrimaryButton>
      }
    >
      <Segmented
        label="What is needed"
        value={draft.unit.kind as Kind}
        onChange={(kind) => setDraftUnit(CREW_TYPES.find((u) => u.kind === kind)!)}
        options={CREW_TYPES.map((u) => ({ id: u.kind as Kind, label: u.label, icon: KIND_ICON[u.kind] }))}
      />

      <div>
        <SectionLabel>Where</SectionLabel>
        <RoadField
          value={destination}
          picking={picking}
          placeholder="Search a road"
          onPickOnMap={() => setInteractionMode(picking ? "idle" : "pick-destination")}
          onChange={(road) => {
            setInteractionMode("idle");
            if (road) setDraftPoint("destination", road);
            else useEmergencyStore.setState((s) => (s.draft ? { draft: { ...s.draft, destination: null } } : {}));
          }}
        />
      </div>

      <div>
        <SectionLabel aside={nearby.length ? `${free} of ${nearby.length} free` : undefined}>
          {destination ? "Closest crews" : "Crews"}
        </SectionLabel>
        {nearby.length === 0 ? (
          <p className="rounded-2xl bg-surface-fill px-3 py-2.5 text-[13px] text-muted-foreground">
            No {KIND_NOUN[kind]} crew is signed in. A crew appears here when its driver logs in.
          </p>
        ) : (
          <Group>
            {nearby.slice(0, 4).map((n) => (
              <FleetRow key={n.unit.unitId} entry={n} kind={kind} />
            ))}
          </Group>
        )}
      </div>

      {error && <InlineError>{error}</InlineError>}
    </Sheet>
  );
}

async function sendCall(call: PendingCall) {
  await postCommand({
    event_type: "EmergencyRequestCreated",
    payload: {
      request_id: call.requestId,
      // Deliberately empty: sim-service offers the call to the nearest crew
      // of `vehicle_kind` and the request takes that unit's id when one of
      // them accepts. The unit sets off from wherever it is, so the source is
      // not the operator's to choose; the field is required by the schema and
      // carries the scene.
      vehicle_id: "",
      vehicle_kind: KIND_EVENT[call.unit.kind],
      source_edge: call.destination.edgeId,
      destination_edge: call.destination.edgeId,
      priority: 1,
      requested_at: Date.now(),
    },
  });
}

type FleetStatus = "available" | "busy" | "off";
interface Ranked {
  unit: FleetUnit;
  status: FleetStatus;
  distM: number | null;
}

/** Units of `kind`, free ones first, then by straight-line distance to the
 *  scene. Only a preview: the dispatcher ranks by live travel time. */
function rankFleet(fleet: FleetUnit[], kind: Kind, at: [number, number] | null): Ranked[] {
  const order: Record<FleetStatus, number> = { available: 0, busy: 1, off: 2 };
  return fleet
    .filter((u) => u.kind === kind)
    .map((unit) => ({
      unit,
      status: (!unit.onDuty ? "off" : unit.busy ? "busy" : "available") as FleetStatus,
      distM: at && unit.at ? haversineMeters(unit.at, at) : null,
    }))
    .sort(
      (a, b) =>
        order[a.status] - order[b.status] ||
        (a.distM ?? Infinity) - (b.distM ?? Infinity) ||
        a.unit.callSign.localeCompare(b.unit.callSign),
    );
}

function FleetRow({ entry, kind }: { entry: Ranked; kind: Kind }) {
  const { unit, status, distM } = entry;
  const label = { available: "Available", busy: "On a call", off: "Off duty" }[status];
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      <span
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-full [&_svg]:size-4",
          status === "available" ? "bg-status-ok-muted text-status-ok" : "bg-muted text-muted-foreground",
        )}
      >
        {KIND_ICON[kind]}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium leading-tight">{unit.callSign}</p>
        <p className="truncate text-[12px] text-muted-foreground">
          {unit.edgeId ? `Near ${roadLabel(unit.edgeId)}` : "Position unknown"}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p
          className={cn(
            "text-[12px] font-medium",
            status === "available" ? "text-status-ok" : "text-muted-foreground",
          )}
        >
          {label}
        </p>
        {distM != null && (
          <p className="tabular text-[12px] text-muted-foreground">{formatKm(distM)}</p>
        )}
      </div>
    </div>
  );
}

function formatKm(m: number) {
  return m < 950 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}

// ---- 2. finding a crew -----------------------------------------------------

const OFFER_SECONDS = 25;

function PendingCallSheet({ call }: { call: PendingCall }) {
  const status = useCrewStore((s) => s.calls[call.requestId]);
  const requests = useEmergencyStore((s) => s.requests);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const setPendingCall = useEmergencyStore((s) => s.setPendingCall);
  const label = useUnitLabel();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const kind = call.unit.kind;

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, []);

  // A crew accepted: the call is now a request with a route. Show that.
  const accepted = requests.find((r) => r.id === call.requestId);
  useEffect(() => {
    if (accepted) {
      selectRequest(accepted.id);
      setPendingCall(null);
    }
  }, [accepted, selectRequest, setPendingCall]);

  const close = () => setPendingCall(null);
  const cancel = async () => {
    setBusy(true);
    try {
      await postCommand({
        event_type: "EmergencyCommand",
        payload: { request_id: call.requestId, action: "CANCEL", requested_at: Date.now() },
      });
      close();
    } catch (err) {
      setError(errorText(err, "Could not cancel."));
      setBusy(false);
    }
  };
  const retry = async () => {
    setBusy(true);
    setError(null);
    const again = { ...call, requestId: crypto.randomUUID(), sentAtMs: Date.now() };
    try {
      await sendCall(again);
      setPendingCall(again);
    } catch (err) {
      setError(errorText(err, "Could not send the request."));
    } finally {
      setBusy(false);
    }
  };

  const state = status?.state;
  const nobody = state === "exhausted";
  const left = status && state === "offered" ? Math.max(0, OFFER_SECONDS - (now - status.atMs) / 1000) : 0;
  const waitedS = (now - call.sentAtMs) / 1000;

  let headline: string;
  let detail: string;
  if (nobody) {
    headline = `No ${KIND_NOUN[kind]} took the call`;
    detail = status?.asked.length
      ? `Asked ${status.asked.map(label).join(", ")}. Everyone else is busy or off duty.`
      : `No ${KIND_NOUN[kind]} crew is free right now.`;
  } else if (state === "offered") {
    headline = `Asking ${label(status!.unitId)}`;
    detail = `${mmss(status!.etaS)} away · waiting for the crew to accept`;
  } else if (state === "accepted") {
    headline = `${label(status!.unitId)} accepted`;
    detail = "Planning the route…";
  } else if (state === "declined" || state === "expired") {
    headline = "Asking the next crew";
    detail = `${label(status!.unitId)} ${state === "declined" ? "couldn't take it" : "didn't answer"}.`;
  } else {
    headline = `Finding the nearest ${KIND_NOUN[kind]}`;
    detail =
      waitedS > 8
        ? "No answer from the simulation yet. Is sim-service running in live mode?"
        : "Checking who is free and how fast they can get there…";
  }

  return (
    <Sheet
      title={headline}
      subtitle={`To ${roadLabel(call.destination.edgeId)}`}
      icon={KIND_ICON[kind]}
      onClose={close}
      footer={
        nobody ? (
          <div className="flex gap-2">
            <SecondaryButton onClick={close}>Close</SecondaryButton>
            <SecondaryButton onClick={retry} disabled={busy}>
              <RefreshCw className={cn(busy && "animate-spin")} />
              Try again
            </SecondaryButton>
          </div>
        ) : (
          <SecondaryButton tone="critical" onClick={cancel} disabled={busy}>
            {busy ? "Cancelling…" : "Cancel request"}
          </SecondaryButton>
        )
      }
    >
      <div className="flex items-start gap-3 rounded-2xl bg-surface-fill px-3 py-3">
        {nobody ? (
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-status-warn" />
        ) : (
          <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-primary" />
        )}
        <p className="text-[13px] leading-snug text-muted-foreground">{detail}</p>
      </div>

      {state === "offered" && (
        <div aria-hidden className="h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500 ease-linear"
            style={{ width: `${(left / OFFER_SECONDS) * 100}%` }}
          />
        </div>
      )}

      {status && status.asked.length > 0 && !nobody && (
        <div>
          <SectionLabel>Already asked</SectionLabel>
          <Group>
            {status.asked.map((u) => (
              <div key={u} className="flex items-center justify-between px-3 py-2 text-[13px]">
                <span>{label(u)}</span>
                <span className="text-muted-foreground">No</span>
              </div>
            ))}
          </Group>
        </div>
      )}

      {error && <InlineError>{error}</InlineError>}
    </Sheet>
  );
}

// ---- 3. the mission ----------------------------------------------------------

type BusyKind = "corridor" | "cancel" | "recalc";

/** The ambulance's patient leg that belongs to this request, if any. */
function useHospitalFor(request: EmergencyRequest): HospitalMission | null {
  const mission = useCrewStore((s) => s.hospital[request.vehicleId]);
  if (!mission) return null;
  const scene = request.id.replace(/-hospital-\d+$/, "");
  return mission.requestId === scene ? mission : null;
}

function RoutePreview({ request }: { request: EmergencyRequest }) {
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const archiveRequest = useEmergencyStore((s) => s.archiveRequest);
  const previewRank = useEmergencyStore((s) => s.previewRank);
  const setPreviewRank = useEmergencyStore((s) => s.setPreviewRank);
  const label = useUnitLabel();
  const hospital = useHospitalFor(request);
  const [busy, setBusy] = useState<null | BusyKind>(null);
  const [error, setError] = useState<string | null>(null);

  const routes = requestRoutes(request);
  const active = routes[0] ?? null; // the one the backend dispatches
  const previewed = routes[previewRank] ?? active;
  const isPreviewingAlt = previewed != null && previewed !== active;
  const reroutable = request.state === "route_ready" || request.state === "in_transit";
  const terminal = isTerminalRequest(request);
  const toHospital = /-hospital-\d+$/.test(request.id);
  const kind = kindOf(request.vehicleKind);

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

  const etaS = request.live?.etaS ?? previewed?.etaS ?? null;
  const distM = previewed?.totalDistanceM ?? null;
  const destination = toHospital
    ? hospital?.options.find((o) => o.facilityId === hospital.chosenId)?.name ?? roadLabel(request.destinationEdge)
    : roadLabel(request.destinationEdge);

  return (
    <Sheet
      title={label(request.vehicleId)}
      subtitle={`${toHospital ? "Taking patient to" : "To"} ${destination}`}
      icon={toHospital ? <Hospital /> : KIND_ICON[kind]}
      onClose={() => selectRequest(null)}
      footer={
        terminal ? undefined : (
          <div className="space-y-2">
            {active && request.state === "route_ready" && (
              <PrimaryButton onClick={() => send("ACTIVATE_CORRIDOR", "corridor")} disabled={busy != null}>
                {busy === "corridor" ? <Loader2 className="animate-spin" /> : <RouteIcon />}
                Start with green corridor
              </PrimaryButton>
            )}
            <div className="flex gap-2">
              {reroutable && (
                <SecondaryButton onClick={() => send("RECALCULATE", "recalc")} disabled={busy != null}>
                  <RefreshCw className={cn(busy === "recalc" && "animate-spin")} />
                  {busy === "recalc" ? "Re-planning…" : "Re-plan"}
                </SecondaryButton>
              )}
              <SecondaryButton tone="critical" onClick={() => send("CANCEL", "cancel")} disabled={busy != null}>
                {busy === "cancel" ? "Cancelling…" : "Stand down"}
              </SecondaryButton>
            </div>
          </div>
        )
      }
    >
      {terminal ? (
        <MissionSummary
          request={request}
          hospital={hospital}
          onDismiss={() => {
            archiveRequest(request.id);
            selectRequest(null);
          }}
        />
      ) : (
        <>
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="tabular text-[34px] font-semibold leading-none tracking-[-0.02em] text-status-ok">
                {etaS != null ? mmss(etaS) : "–"}
              </p>
              <p className="mt-1.5 text-[13px] text-muted-foreground">
                {distM != null ? `${(distM / 1000).toFixed(1)} km` : ""}
                {etaS != null ? ` · arrives ${clock(etaS)}` : ""}
              </p>
            </div>
            <StatePill state={request.state} />
          </div>

          {request.state === "routing" && (
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Planning the route…
            </p>
          )}

          {hospital && hospital.state === "at_scene" && !toHospital && <HospitalStatus mission={hospital} />}

          {request.detail && /reroute/i.test(request.detail) && (
            <Notice tone="warn" icon={<RefreshCw />}>
              {request.detail.replace(/^auto-reroute — /, "Re-routed: ")}
            </Notice>
          )}

          {previewed && previewed.forcedThrough.length > 0 && (
            <Notice tone="critical" icon={<AlertTriangle />}>
              The only route crosses {previewed.forcedThrough.length} blocked segment
              {previewed.forcedThrough.length > 1 ? "s" : ""}. The vehicle can get through, slowly.
            </Notice>
          )}

          {routes.length > 1 && (
            <RouteTabs routes={routes} previewRank={previewRank} onPick={setPreviewRank} />
          )}
          {isPreviewingAlt && (
            <p className="text-[12px] text-muted-foreground">
              Previewing an alternative. The recommended route is the one the crew drives; re-plan to
              choose again from current traffic.
            </p>
          )}

          {request.corridor && request.state !== "route_ready" && (
            <CorridorStatus corridor={request.corridor} live={request.live} />
          )}

          {error && <InlineError>{error}</InlineError>}

          {previewed && <RouteDetails route={previewed} request={request} />}
        </>
      )}
    </Sheet>
  );
}

function clock(etaS: number) {
  return new Date(Date.now() + etaS * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Notice({
  tone,
  icon,
  children,
}: {
  tone: "warn" | "critical" | "ok";
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-xl px-3 py-2 text-[13px] leading-snug [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0",
        tone === "warn" && "bg-status-warn-muted text-status-warn",
        tone === "critical" && "bg-status-critical-muted text-status-critical",
        tone === "ok" && "bg-status-ok-muted text-status-ok",
      )}
    >
      {icon}
      <span>{children}</span>
    </p>
  );
}

/** At the scene: the crew is choosing where to take the patient. */
function HospitalStatus({ mission }: { mission: HospitalMission }) {
  const rec = mission.options.find((o) => o.facilityId === mission.recommendedId);
  return (
    <Notice tone="ok" icon={<Hospital />}>
      At the scene. The crew is choosing a hospital
      {rec ? `; suggested ${rec.name} (${mmss(rec.etaS)})` : ""}.
    </Notice>
  );
}

/** Numbers behind the route, for whoever wants them, folded away by default. */
function RouteDetails({ route, request }: { route: EmergencyRouteView; request: EmergencyRequest }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-2xl bg-surface-fill">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-3 py-2.5 text-[13px] font-medium text-foreground"
      >
        Route details
        <ChevronRight className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="space-y-3 px-3 pb-3">
          <div className="grid grid-cols-3 gap-2">
            <Metric label="Junctions" value={String(route.nIntersections)} />
            <Metric label="Signals" value={String(route.signalisedIntersections.length)} />
            <Metric label="Signal wait" value={`${Math.round(route.cost.signalDelayS)} s`} />
            <Metric
              label="Congested"
              value={String(route.congestedSegments.length)}
              tone={route.congestedSegments.length ? "bad" : undefined}
            />
            <Metric label="Avoided" value={String(route.anomalousSegmentsAvoided.length)} />
            <Metric label="Reliable" value={route.reliable ? "Yes" : "Low"} tone={route.reliable ? undefined : "bad"} />
          </div>
          <WhyThisRoute route={route} />
          <Timeline entries={request.timeline} />
        </div>
      )}
    </div>
  );
}

function MissionSummary({
  request,
  hospital,
  onDismiss,
}: {
  request: EmergencyRequest;
  hospital: HospitalMission | null;
  onDismiss: () => void;
}) {
  const requests = useEmergencyStore((s) => s.requests);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const route = request.route;
  const reroutes = rerouteCount(request);
  const cancelled = request.state === "cancelled";
  // The ambulance went on to a hospital: follow it there.
  const leg = requests
    .filter((r) => r.id.startsWith(`${request.id}-hospital-`) && !isTerminalRequest(r))
    .sort((a, b) => b.id.localeCompare(a.id))[0];
  const chosen = hospital?.options.find((o) => o.facilityId === hospital.chosenId);

  return (
    <div className="space-y-3">
      <Notice tone={cancelled ? "critical" : "ok"} icon={cancelled ? <X /> : <Check />}>
        {/* No clock time: the request's timestamps are on the simulation's
            clock, which is not the wall clock the operator reads. */}
        {cancelled ? (
          <>
            <span className="font-medium">Stood down</span> · {request.detail || "cancelled before arrival"}
          </>
        ) : (
          <span className="font-medium">
            {/-hospital-\d+$/.test(request.id) ? "Patient delivered" : "Arrived at the scene"}
          </span>
        )}
      </Notice>

      {hospital && !cancelled && (
        <Group>
          <div className="flex items-center gap-3 px-3 py-2.5">
            <Hospital className="size-4 shrink-0 text-muted-foreground" />
            <p className="min-w-0 flex-1 text-[13px]">
              {hospital.state === "at_scene" && "With the patient, choosing a hospital"}
              {hospital.state === "to_hospital" && `Taking the patient to ${chosen?.name ?? "hospital"}`}
              {hospital.state === "done" &&
                (chosen ? `Patient delivered to ${chosen.name}` : "No hospital reachable by road")}
            </p>
          </div>
          {leg && (
            <button
              type="button"
              onClick={() => selectRequest(leg.id)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-[13px] font-medium text-primary"
            >
              Follow to hospital
              <ChevronRight className="size-4" />
            </button>
          )}
        </Group>
      )}

      <Group>
        <SummaryRow label="Unit" value={unitName(request.vehicleId)} />
        <SummaryRow label="To" value={roadLabel(request.destinationEdge)} />
        {route && <SummaryRow label="Distance" value={`${(route.totalDistanceM / 1000).toFixed(1)} km`} />}
        {route && <SummaryRow label="Planned time" value={mmss(route.totalTravelTimeS)} />}
        <SummaryRow label="Re-routes" value={String(reroutes)} />
        <SummaryRow
          label="Green corridor"
          value={request.corridor ? CORRIDOR_STATUS_META[request.corridor.status].label : "None"}
        />
      </Group>

      <SecondaryButton onClick={onDismiss}>Dismiss</SecondaryButton>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2 text-[13px]">
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
    <div role="tablist" aria-label="Routes" className="flex gap-1 rounded-[12px] bg-surface-fill p-1">
      {routes.map((rt, i) => (
        <button
          key={i}
          type="button"
          role="tab"
          aria-selected={i === previewRank}
          onClick={() => onPick(i)}
          className={cn(
            "flex-1 rounded-[9px] px-2 py-1.5 text-center transition-[background-color,box-shadow] duration-150",
            i === previewRank ? "bg-surface-raised shadow-elevation-1" : "hover:bg-muted",
          )}
        >
          <span className="block text-[12px] font-medium">{i === 0 ? "Fastest" : `Option ${i + 1}`}</span>
          <span className="tabular block text-[12px] text-muted-foreground">{mmss(rt.etaS)}</span>
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
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1 text-[12px] font-medium text-primary"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        Why this route?
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <ul className="space-y-0.5">
            {parts.map(([name, v]) => (
              <li key={name} className="flex justify-between text-[12px]">
                <span className="text-muted-foreground">{name}</span>
                <span className="tabular">{v.toFixed(2)}</span>
              </li>
            ))}
            <li className="flex justify-between border-t border-border pt-1 text-[12px] font-medium">
              <span>score (lower is better)</span>
              <span className="tabular">{route.cost.score.toFixed(2)}</span>
            </li>
          </ul>
          {weights.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {weights.map(([k, v]) => (
                <span key={k} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {WEIGHT_LABEL[k]} × {Number(v).toFixed(2)}
                </span>
              ))}
            </div>
          )}
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
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mb-1.5 flex items-center gap-1 text-[12px] font-medium text-primary"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        History ({entries.length})
      </button>
      <ol className="space-y-1.5">
        {shown.map((t, i) => (
          <li key={`${t.atMs}-${i}`} className="flex gap-2 text-[12px]">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/70" />
            <div className="min-w-0">
              <span className="font-medium capitalize">{t.state.replace(/_/g, " ").toLowerCase()}</span>
              <span className="ml-1.5 text-muted-foreground">{relTime(t.atMs)}</span>
              {t.detail && <p className="truncate text-muted-foreground">{t.detail}</p>}
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
  { label: string; tone: "ok" | "warn" | "critical" | "muted"; pulse: boolean }
> = {
  proposed: { label: "Proposed", tone: "muted", pulse: false },
  active: { label: "Active", tone: "ok", pulse: true },
  restoring: { label: "Restoring", tone: "warn", pulse: true },
  completed: { label: "Completed", tone: "muted", pulse: false },
  cancelled: { label: "Cancelled", tone: "critical", pulse: false },
};

const TONE_TEXT = {
  ok: "text-status-ok",
  warn: "text-status-warn",
  critical: "text-status-critical",
  muted: "text-muted-foreground",
} as const;
const TONE_DOT = {
  ok: "bg-status-ok",
  warn: "bg-status-warn",
  critical: "bg-status-critical",
  muted: "bg-muted-foreground",
} as const;

function CorridorStatus({ corridor, live }: { corridor: GreenCorridorView; live?: EmergencyVehicleLive }) {
  const passed = new Set(corridor.passedIntersections);
  const ordered = orderedReservations(corridor);
  const total = ordered.length;
  const done = ordered.filter((r) => passed.has(r.intersectionId)).length;
  const next = nextCorridorReservation(corridor);
  const progressPct = live ? Math.round(live.routeProgress * 100) : 0;
  const meta = CORRIDOR_STATUS_META[corridor.status];

  return (
    <div className="space-y-2.5 rounded-2xl bg-surface-fill p-3">
      <div className="flex items-center justify-between">
        <span className={cn("flex items-center gap-2 text-[13px] font-medium", TONE_TEXT[meta.tone])}>
          <span className="relative flex size-2">
            {meta.pulse && (
              <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", TONE_DOT[meta.tone])} />
            )}
            <span className={cn("relative inline-flex size-2 rounded-full", TONE_DOT[meta.tone])} />
          </span>
          Green corridor · {meta.label}
        </span>
        <span className="tabular text-[12px] text-muted-foreground">
          {done}/{total} signals
        </span>
      </div>

      {next && (
        <p className="truncate text-[12px] text-muted-foreground">
          Next: <span className="font-medium text-foreground">{shortJunctionName(next.intersectionId)}</span> · held
          ~{corridorHoldSeconds(next)} s
        </p>
      )}

      {total > 0 && (
        <div className="flex gap-1" aria-hidden>
          {ordered.map((r) => {
            const isPassed = passed.has(r.intersectionId);
            const isNext = next?.intersectionId === r.intersectionId;
            return (
              <span
                key={r.intersectionId}
                title={`${shortJunctionName(r.intersectionId)} · ~${corridorHoldSeconds(r)} s hold`}
                className={cn(
                  "h-1.5 flex-1 rounded-full",
                  isPassed ? "bg-muted-foreground/30" : isNext ? "bg-status-ok" : "bg-status-ok/35",
                )}
              />
            );
          })}
        </div>
      )}

      {live && (
        <div className="flex items-center justify-between text-[12px] text-muted-foreground">
          <span>{progressPct}% of the way</span>
          {live.speedMps > 0 && <span className="tabular">{Math.round(live.speedMps * 3.6)} km/h</span>}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-xl bg-surface-raised px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "tabular text-[15px] font-semibold",
          tone === "good" && "text-status-ok",
          tone === "bad" && "text-status-warn",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function StatePill({ state }: { state: EmergencyRequest["state"] }) {
  const map: Record<EmergencyRequest["state"], [string, string]> = {
    created: ["Created", "bg-muted text-muted-foreground"],
    routing: ["Routing", "bg-status-info-muted text-status-info"],
    route_ready: ["Ready", "bg-status-ok-muted text-status-ok"],
    green_corridor_active: ["Corridor on", "bg-status-ok-muted text-status-ok"],
    in_transit: ["En route", "bg-status-info-muted text-status-info"],
    completed: ["Arrived", "bg-muted text-muted-foreground"],
    cancelled: ["Stood down", "bg-status-critical-muted text-status-critical"],
  };
  const [label, cls] = map[state];
  return <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[12px] font-medium", cls)}>{label}</span>;
}
