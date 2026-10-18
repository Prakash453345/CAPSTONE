import { CheckCircle2, MapPinned, Radio, Route as RouteIcon, Siren, TriangleAlert, Waypoints } from "lucide-react";
import { Button, EmptyState, Panel, PanelHeader, Pill } from "@/components/console/kit";
import { STATE_WORDS, mmss, networkMood } from "@/components/console/words";
import { toneText } from "@/components/console/tone";
import { ManeuverIcon } from "@/components/crew/ManeuverBanner";
import { roadLabel } from "@/data/network";
import { formatDistance } from "@/crew/plan";
import type { Mission } from "@/crew/useMission";
import { rerouteCount } from "@/store/emergencyStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useSystemStore } from "@/store/systemStore";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-muted/70 px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted-foreground">{label}</p>
      <p className="tabular mt-0.5 text-[17px] font-semibold leading-tight">{value}</p>
    </div>
  );
}

/** No mission yet: the unit is available and the road is quiet or busy. */
export function StandbyCard({ unitName, weatherAdvice }: { unitName: string | null; weatherAdvice: string | null }) {
  const congestion = useSystemStore((s) => (s.summary.lastUpdate ? s.summary.congestion : null));
  const anomalies = useIncidentStore((s) => s.anomalies.filter((a) => a.status === "active").length);
  const mood = networkMood(congestion);
  return (
    <Panel className="pointer-events-auto" aria-labelledby="standby-title">
      <div className="flex items-center gap-3.5 px-5 pb-4 pt-5">
        <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-2xl bg-muted text-muted-foreground">
          <Siren className="size-5" strokeWidth={1.8} />
        </span>
        <div className="min-w-0">
          <h2 id="standby-title" className="truncate text-[16px] font-semibold tracking-[-0.01em]">
            {unitName ? `${unitName} is standing by` : "Choose your vehicle"}
          </h2>
          <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">
            {unitName ? "Your route appears here when dispatch sends a call." : "Pick the unit you are driving to follow its calls."}
          </p>
        </div>
      </div>
      {unitName && (
        <ul className="space-y-2.5 border-t border-border px-5 py-3.5 text-[13px]">
          <li className="flex items-center gap-2.5">
            <Radio className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className={toneText(mood.tone)}>{mood.headline}</span>
          </li>
          <li className="flex items-center gap-2.5 text-muted-foreground">
            <TriangleAlert className="size-4 shrink-0" aria-hidden />
            {anomalies ? `${anomalies} disruption${anomalies === 1 ? "" : "s"} on the road right now` : "No disruptions reported"}
          </li>
          {weatherAdvice && <li className="text-status-warn">{weatherAdvice}</li>}
        </ul>
      )}
    </Panel>
  );
}

/** A call has been assigned but the vehicle is not moving yet. */
export function BriefingCard({ mission, onDirections }: { mission: Mission; onDirections: () => void }) {
  const { request, plan } = mission;
  const route = request.route;
  const state = STATE_WORDS[request.state];
  const from = roadLabel(request.sourceEdge);
  const to = roadLabel(request.destinationEdge);
  const first = plan?.maneuvers.slice(1, 4) ?? [];

  return (
    <Panel className="pointer-events-auto" aria-labelledby="briefing-title">
      <PanelHeader id="briefing-title" title="Your next call" subtitle={`${from} to ${to}`} actions={<Pill tone={state.tone} dot>{state.label}</Pill>} />
      {route ? (
        <div className="space-y-3 px-5 pb-4">
          <div className="grid grid-cols-3 gap-2">
            <Fact label="Estimated" value={mmss(route.etaS)} />
            <Fact label="Distance" value={formatDistance(route.totalDistanceM)} />
            <Fact label="Signals" value={String(route.signalisedIntersections.length)} />
          </div>
          {route.forcedThrough.length > 0 && (
            <p role="alert" className="flex items-start gap-2 rounded-xl bg-status-critical-muted px-3 py-2.5 text-[13px] text-status-critical">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              This route crosses a blocked road because there is no other way. Expect delay.
            </p>
          )}
          {route.anomalousSegmentsAvoided.length > 0 && (
            <p className="flex items-center gap-2 text-[13px] text-status-ok">
              <CheckCircle2 className="size-4" aria-hidden />
              Avoids {route.anomalousSegmentsAvoided.length} disruption{route.anomalousSegmentsAvoided.length === 1 ? "" : "s"}.
            </p>
          )}
          {first.length > 0 && (
            <ol className="space-y-1.5">
              {first.map((m) => (
                <li key={m.id} className="flex items-center gap-3 text-[13.5px]">
                  <span className="size-5 shrink-0 text-primary">
                    <ManeuverIcon m={m} />
                  </span>
                  <span className="min-w-0 flex-1 truncate">{m.text}</span>
                  <span className="tabular text-muted-foreground">{formatDistance(m.atM)}</span>
                </li>
              ))}
            </ol>
          )}
          <Button variant="secondary" icon={Waypoints} className="w-full" onClick={onDirections}>
            See all directions
          </Button>
        </div>
      ) : (
        <p className="flex items-center gap-2 px-5 pb-5 text-[13px] text-muted-foreground">
          <RouteIcon className="size-4" aria-hidden />
          Dispatch is finding the best route. It will appear here.
        </p>
      )}
    </Panel>
  );
}

/** The run is over. */
export function ArrivalCard({ mission, onDone }: { mission: Mission; onDone: () => void }) {
  const cancelled = mission.request.state === "cancelled";
  const passed = mission.corridor?.passedIntersections.length ?? 0;
  const reroutes = rerouteCount(mission.request);
  return (
    <Panel className="pointer-events-auto" aria-labelledby="arrival-title">
      <div className="flex flex-col items-center px-6 pb-5 pt-7 text-center">
        <span className="grid size-14 place-items-center rounded-2xl bg-status-ok-muted text-status-ok">
          {cancelled ? <MapPinned className="size-7" /> : <CheckCircle2 className="size-7" />}
        </span>
        <h2 id="arrival-title" className="mt-4 text-xl font-semibold tracking-[-0.01em]">
          {cancelled ? "This call was stood down" : "You have arrived"}
        </h2>
        <p className="mt-1 text-[13px] text-muted-foreground">{roadLabel(mission.request.destinationEdge)}</p>
        {!cancelled && (
          <div className="mt-5 grid w-full grid-cols-3 gap-2">
            <Fact label="Distance" value={formatDistance(mission.plan?.totalM ?? mission.request.route?.totalDistanceM ?? 0)} />
            <Fact label="Signals cleared" value={String(passed)} />
            <Fact label="Re-routes" value={String(reroutes)} />
          </div>
        )}
        <Button variant="primary" className="mt-5 w-full" onClick={onDone}>
          Back to standby
        </Button>
      </div>
    </Panel>
  );
}

/** Every instruction on the route with how far from the start it happens. */
export function DirectionsCard({ mission, onClose }: { mission: Mission; onClose: () => void }) {
  const plan = mission.plan;
  return (
    <Panel className="pointer-events-auto" aria-labelledby="directions-title">
      <PanelHeader
        id="directions-title"
        title="All directions"
        subtitle={plan ? `${formatDistance(plan.totalM)} in total` : undefined}
        actions={
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      />
      <ol className="px-3 pb-3">
        {(plan?.maneuvers ?? []).map((m) => {
          const done = m.atM < mission.alongM - 3 && m.kind !== "depart";
          return (
            <li key={m.id} className="flex items-center gap-3 rounded-xl px-2 py-2.5" aria-current={mission.next?.id === m.id ? "step" : undefined}>
              <span className={`grid size-9 shrink-0 place-items-center rounded-full p-2 ${mission.next?.id === m.id ? "bg-primary text-primary-foreground" : "bg-muted text-foreground/80"}`}>
                <ManeuverIcon m={m} />
              </span>
              <span className={`min-w-0 flex-1 text-[14px] ${done ? "text-muted-foreground line-through" : "font-medium"}`}>{m.text}</span>
              <span className="tabular shrink-0 text-[13px] text-muted-foreground">{formatDistance(m.atM)}</span>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

/** A crew account that has not been linked to a vehicle yet. */
export function NoVehicleCard() {
  return (
    <Panel className="pointer-events-auto">
      <EmptyState
        icon={Siren}
        title="No vehicle is linked to your account"
        body="Ask dispatch to link this account to your vehicle. Your route appears here once they do."
      />
    </Panel>
  );
}
