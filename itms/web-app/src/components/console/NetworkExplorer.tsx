import { useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Radio, Search, Waypoints } from "lucide-react";
import { edgeById, roadEdges, roadLabel, shortJunctionName, signalJunctions } from "@/data/network";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { EmptyState, Meter, Pill, Segmented } from "@/components/console/kit";
import { EASE_OUT } from "@/components/console/motion";
import { toneText } from "@/components/console/tone";
import { congestionTone, congestionWord } from "@/components/console/words";
import { cn } from "@/utils/cn";

type Tab = "roads" | "signals";

/** How long the street list keeps its order before it may re-sort by congestion. */
const RESORT_EVERY_MS = 4000;

function focusEdge(edgeId: string) {
  const e = edgeById.get(edgeId);
  if (!e) return;
  const p = e.path[Math.floor(e.path.length / 2)]!;
  useMapStore.getState().focusOn({ longitude: p[0], latitude: p[1] }, 16.5);
}

/** The Traffic page's side panel: streets and signals, worst first. */
export function NetworkExplorer() {
  const [tab, setTab] = useState<Tab>("roads");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-4 pb-3 pt-4">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          ariaLabel="Show"
          className="w-full"
          options={[
            { value: "roads", label: "Roads", icon: Waypoints },
            { value: "signals", label: "Signals", icon: Radio },
          ]}
        />
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          initial={{ opacity: 0, x: tab === "roads" ? -8 : 8 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: EASE_OUT }}
          className="flex min-h-0 flex-1 flex-col"
        >
          {tab === "roads" ? <Roads /> : <Signals />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

interface Street {
  name: string;
  worst: number | undefined;
  km: number;
  segments: { id: string; value: number | undefined; lanes: number; m: number }[];
}

function Roads() {
  const congestion = useTrafficStore((s) => s.roadCongestion);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  // hold the order still while the pointer is over the list, so rows never jump under it
  const hovering = useRef(false);
  const lastOrder = useRef<string[]>([]);
  const lastSortAt = useRef(0);

  const streets = useMemo(() => {
    const map = new Map<string, Street>();
    for (const e of roadEdges) {
      const name = roadLabel(e);
      const s = map.get(name) ?? { name, worst: undefined, km: 0, segments: [] };
      const v = congestion[e.id];
      s.km += e.lengthM / 1000;
      s.segments.push({ id: e.id, value: v, lanes: e.numLanes, m: e.lengthM });
      if (v != null && (s.worst == null || v > s.worst)) s.worst = v;
      map.set(name, s);
    }
    let list = [...map.values()];
    for (const s of list) s.segments.sort((a, b) => (b.value ?? -1) - (a.value ?? -1));
    // Values update live, but the order only changes every few seconds (and
    // never under the pointer): re-sorting every tick made rows jump around.
    const settled = Date.now() - lastSortAt.current < RESORT_EVERY_MS;
    if ((hovering.current || settled) && lastOrder.current.length) {
      const rank = new Map(lastOrder.current.map((n, i) => [n, i]));
      list.sort((a, b) => (rank.get(a.name) ?? 99) - (rank.get(b.name) ?? 99));
    } else {
      list.sort((a, b) => (b.worst ?? -1) - (a.worst ?? -1));
      lastOrder.current = list.map((s) => s.name);
      lastSortAt.current = Date.now();
    }
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((s) => s.name.toLowerCase().includes(q) || s.segments.some((g) => g.id.includes(q)));
    return list;
  }, [congestion, query]);

  return (
    <>
      <label className="mx-4 mb-2 flex h-9 items-center gap-2 rounded-xl bg-muted px-3 text-muted-foreground focus-within:ring-2 focus-within:ring-ring/40">
        <Search className="size-4 shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a street"
          aria-label="Find a street"
          className="min-w-0 flex-1 bg-transparent text-[13.5px] text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
      </label>
      <div
        className="min-h-0 flex-1 overflow-y-auto px-2 pb-3"
        onMouseEnter={() => (hovering.current = true)}
        onMouseLeave={() => (hovering.current = false)}
      >
        {streets.length === 0 && <EmptyState icon={Search} title="No matching streets" body="Try another name." />}
        <ul>
          {streets.map((s) => {
            const tone = congestionTone(s.worst);
            const expanded = open === s.name;
            return (
              <motion.li key={s.name} layout="position" transition={{ duration: 0.35, ease: EASE_OUT }}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => {
                    setOpen(expanded ? null : s.name);
                    const worst = s.segments[0];
                    if (worst) focusEdge(worst.id);
                  }}
                  className={cn("w-full rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted", expanded && "bg-muted")}
                >
                  <span className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-foreground">{s.name}</span>
                    <span className={cn("shrink-0 text-[12.5px] font-medium tabular", toneText(tone))}>
                      {congestionWord(s.worst)}
                      {s.worst != null && ` · ${Math.round(s.worst * 100)}%`}
                    </span>
                    <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-200", expanded && "rotate-180")} />
                  </span>
                  <span className="mt-1 block text-[12px] text-muted-foreground">
                    {s.segments.length} {s.segments.length === 1 ? "segment" : "segments"} · {s.km.toFixed(1)} km
                  </span>
                  <Meter value={s.worst ?? 0} tone={tone} className="mt-2" />
                </button>
                <AnimatePresence initial={false}>
                  {expanded && (
                    <motion.ul
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.28, ease: EASE_OUT }}
                      className="overflow-hidden"
                    >
                      {s.segments.map((g, i) => (
                        <li key={g.id}>
                          <button
                            type="button"
                            onClick={() => focusEdge(g.id)}
                            title={`Edge ${g.id}`}
                            className="flex w-full items-center gap-3 rounded-lg py-1.5 pl-6 pr-3 text-left text-[12.5px] transition-colors hover:bg-muted"
                          >
                            <span className={cn("size-1.5 shrink-0 rounded-full", g.value == null ? "bg-muted-foreground/40" : `bg-current ${toneText(congestionTone(g.value))}`)} />
                            <span className="flex-1 text-muted-foreground">
                              Segment {i + 1} · {g.lanes} {g.lanes === 1 ? "lane" : "lanes"} · {Math.round(g.m)} m
                            </span>
                            <span className="tabular text-foreground">{g.value == null ? "–" : `${Math.round(g.value * 100)}%`}</span>
                          </button>
                        </li>
                      ))}
                    </motion.ul>
                  )}
                </AnimatePresence>
              </motion.li>
            );
          })}
        </ul>
      </div>
    </>
  );
}

const SIGNAL_DOT = { green: "bg-status-ok", yellow: "bg-status-warn", red: "bg-status-critical" } as const;
const SIGNAL_WORD = { green: "Green", yellow: "Amber", red: "Red" } as const;

function Signals() {
  const intersections = useIncidentStore((s) => s.intersections);
  const byId = new Map(intersections.map((i) => [i.id, i]));
  const focusOn = useMapStore((s) => s.focusOn);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
      <p className="px-3 pb-2 text-[12.5px] text-muted-foreground">
        {signalJunctions.length} signalised junctions on the corridor.
      </p>
      <ul>
        {signalJunctions.map((j) => {
          const live = byId.get(j.id);
          const state = live?.signalState;
          return (
            <li key={j.id}>
              <button
                type="button"
                onClick={() => focusOn({ longitude: j.lng, latitude: j.lat }, 17)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-muted">
                  <span className={cn("size-2.5 rounded-full", state ? SIGNAL_DOT[state] : "bg-muted-foreground/40")} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium text-foreground">{shortJunctionName(j.id)}</span>
                  <span className="block text-[12px] text-muted-foreground">
                    {live
                      ? `${SIGNAL_WORD[live.signalState]} · ${live.queueLength} queued · ${Math.round(live.averageSpeed)} km/h`
                      : "No reading yet"}
                  </span>
                </span>
                {live?.fault ? (
                  <Pill tone="critical">Fault</Pill>
                ) : live?.preempted ? (
                  <Pill tone="ok">Held for ambulance</Pill>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
