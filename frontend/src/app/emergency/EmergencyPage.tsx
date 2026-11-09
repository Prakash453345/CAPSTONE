import { motion, AnimatePresence } from "framer-motion";
import { Ambulance, Check, Plus, Siren } from "lucide-react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { WorkspaceLayout } from "@/components/console/WorkspaceLayout";
import { Button, EmptyState, Pill } from "@/components/console/kit";
import { EASE_OUT, listMotion } from "@/components/console/motion";
import { MissionCard } from "@/components/console/briefing";
import { missionFacts } from "@/components/console/briefingData";
import { mmss, STATE_WORDS, unitName } from "@/components/console/words";
import {
  CREW_TYPES,
  isTerminalRequest,
  orderedReservations,
  selectSelectedRequest,
  useEmergencyStore,
  useVisibleRequests,
} from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import { edgeById, routeLabel, shortJunctionName } from "@/data/network";
import { cn } from "@/utils/cn";
import type { EmergencyRequest } from "@/types";

const STEPS: { key: EmergencyRequest["state"][]; label: string }[] = [
  { key: ["created", "routing"], label: "Requested" },
  { key: ["route_ready"], label: "Route ready" },
  { key: ["green_corridor_active"], label: "Corridor active" },
  { key: ["in_transit"], label: "On the way" },
  { key: ["completed"], label: "Arrived" },
];

function stepIndex(state: EmergencyRequest["state"]) {
  const i = STEPS.findIndex((s) => s.key.includes(state));
  return i < 0 ? 0 : i;
}

/**
 * Emergency: every unit on the road beside the map. Selecting one brings the
 * map to it and opens its route; its corridor is listed signal by signal.
 */
export function EmergencyPage() {
  const requests = useVisibleRequests();
  const selected = useEmergencyStore(selectSelectedRequest);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const startDraft = useEmergencyStore((s) => s.startDraft);
  const draft = useEmergencyStore((s) => s.draft);
  const focusOn = useMapStore((s) => s.focusOn);

  const sorted = [...requests].sort((a, b) => Number(isTerminalRequest(a)) - Number(isTerminalRequest(b)));
  const current = selected ?? sorted.find((r) => !isTerminalRequest(r)) ?? null;

  const choose = (r: EmergencyRequest) => {
    const same = selected?.id === r.id;
    selectRequest(same ? null : r.id);
    if (same) return;
    if (r.live?.lat != null && r.live?.lon != null) focusOn({ latitude: r.live.lat, longitude: r.live.lon }, 16);
    else {
      const e = edgeById.get(r.sourceEdge);
      if (e) {
        const mid = e.path[Math.floor(e.path.length / 2)]!;
        focusOn({ longitude: mid[0], latitude: mid[1] }, 16);
      }
    }
  };

  const panel = (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div>
          <h2 className="text-[15px] font-semibold text-foreground">Emergency requests</h2>
          <p className="text-[13px] text-muted-foreground">
            {requests.filter((r) => !isTerminalRequest(r)).length} on the road · {requests.length} today
          </p>
        </div>
        <Button variant="primary" size="sm" icon={Plus} disabled={Boolean(draft)} onClick={() => startDraft(CREW_TYPES[0]!)}>
          Dispatch
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {draft && (
          <div className="mx-2 mb-3 rounded-xl bg-primary-muted px-3.5 py-3 text-[13px] leading-relaxed text-primary">
            Requesting {draft.unit.label.toLowerCase()}. Say where help is needed; the nearest free crew is
            asked and drives from wherever it is.
          </div>
        )}

        {requests.length === 0 && !draft && (
          <EmptyState
            icon={Ambulance}
            title="No units on the road"
            body="Send help to a road: the nearest free crew takes the call, the console plans the fastest route and turns the lights ahead of it green."
            action={
              <Button variant="primary" icon={Plus} onClick={() => startDraft(CREW_TYPES[0]!)}>
                Dispatch a unit
              </Button>
            }
          />
        )}

        <AnimatePresence mode="popLayout">
          {current && (
            <motion.div
              key={current.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE_OUT }}
              className="mx-1 mb-4 rounded-2xl bg-muted/60 p-4"
            >
              <MissionCard request={current} compact />
              <Steps state={current.state} />
              <Corridor request={current} />
            </motion.div>
          )}
        </AnimatePresence>

        {sorted.length > 0 && <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground">All requests</div>}
        <motion.ul variants={listMotion.container} initial="hidden" animate="show">
          {sorted.map((r) => {
            const state = STATE_WORDS[r.state];
            const active = current?.id === r.id;
            const { eta } = missionFacts(r);
            return (
              <motion.li key={r.id} variants={listMotion.item}>
                <button
                  type="button"
                  onClick={() => choose(r)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted",
                    active && "bg-muted",
                    isTerminalRequest(r) && "opacity-60",
                  )}
                >
                  <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-status-critical-muted text-status-critical">
                    <Siren className="size-4" strokeWidth={1.9} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13.5px] font-medium text-foreground">{unitName(r.vehicleId)}</span>
                      <Pill tone={state.tone}>{state.label}</Pill>
                    </span>
                    <span className="mt-0.5 block truncate text-[12.5px] text-muted-foreground">
                      {routeLabel(r.sourceEdge, r.destinationEdge)}
                      {!isTerminalRequest(r) && eta != null && ` · ${mmss(eta)} away`}
                    </span>
                  </span>
                </button>
              </motion.li>
            );
          })}
        </motion.ul>
      </div>
    </div>
  );

  return <WorkspaceLayout label="Emergency requests" panel={panel} map={<TrafficMap />} />;
}

function Steps({ state }: { state: EmergencyRequest["state"] }) {
  if (state === "cancelled") return <p className="mt-4 text-[13px] text-muted-foreground">This request was stood down.</p>;
  const at = stepIndex(state);
  return (
    <ol className="mt-5 grid grid-cols-5 gap-1" aria-label="Progress">
      {STEPS.map((s, i) => {
        const done = i < at || state === "completed";
        const now = i === at && state !== "completed";
        return (
          <li key={s.label} className="flex flex-col items-center text-center">
            <span
              className={cn(
                "grid size-6 place-items-center rounded-full text-[11px] font-semibold transition-colors duration-300",
                done && "bg-status-ok text-white",
                now && "bg-primary text-primary-foreground ring-4 ring-primary/20",
                !done && !now && "bg-surface text-muted-foreground shadow-elevation-1",
              )}
            >
              {done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className={cn("mt-1.5 text-[11px] leading-tight", now ? "font-medium text-foreground" : "text-muted-foreground")}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Corridor({ request }: { request: EmergencyRequest }) {
  const reservations = request.corridor ? orderedReservations(request.corridor) : [];
  const passed = new Set(request.corridor?.passedIntersections ?? []);
  const ids = reservations.length ? reservations.map((r) => r.intersectionId) : request.route?.signalisedIntersections ?? [];
  if (!ids.length) return null;
  const next = ids.find((id) => !passed.has(id));
  return (
    <div className="mt-5">
      <p className="text-[12px] font-medium text-muted-foreground">Signals on the route</p>
      <ul className="mt-2 space-y-1">
        {ids.map((id) => {
          const done = passed.has(id);
          const isNext = id === next && request.corridor?.status === "active";
          return (
            <li key={id} className="flex items-center gap-2.5 text-[13px]">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  done ? "bg-status-ok" : isNext ? "animate-pulse bg-status-ok" : "bg-muted-foreground/40",
                )}
              />
              <span className={cn("flex-1 truncate", done ? "text-muted-foreground" : "text-foreground")}>{shortJunctionName(id)}</span>
              <span className="text-[12px] text-muted-foreground">{done ? "Cleared" : isNext ? "Green now" : request.corridor ? "Waiting" : "Planned"}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
