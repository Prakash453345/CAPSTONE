import { useEffect, useState, useMemo } from "react";
import { ArrowUpRight, Search, RadioTower, Route, MapPin, Pause, Play, RefreshCw } from "lucide-react";
import { roadEdges } from "@/data/network";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";

function getBucket(v: number | undefined): 0 | 1 | 2 | 3 {
  if (v == null) return 3;
  return v > 0.6 ? 0 : v > 0.35 ? 1 : 2;
}

/** Roads by tier (worst first), then by name — from a `bucketKey` string. */
function sortRoads(bucketKey: string) {
  const tiers = bucketKey.split(",").map(Number);
  const tierOf = new Map(roadEdges.map((e, i) => [e.id, tiers[i] ?? 3]));
  return [...roadEdges].sort((a, b) => {
    const d = (tierOf.get(a.id) ?? 3) - (tierOf.get(b.id) ?? 3);
    return d || (a.name ?? a.id).localeCompare(b.name ?? b.id);
  });
}

export function RoadConditions({ compact = false }: { compact?: boolean }) {
  const liveCongestion = useTrafficStore((s) => s.roadCongestion);
  const focusOn = useMapStore((s) => s.focusOn);
  const [search, setSearch] = useState("");
  // WCAG 2.2.2: auto-updating values can be paused; the list shows a frozen
  // snapshot until resumed, then jumps to the current state.
  const [frozen, setFrozen] = useState<typeof liveCongestion | null>(null);
  const congestion = frozen ?? liveCongestion;

  // Tier per road (critical / warn / ok / no data) as one string, so the
  // sort only recomputes when a road changes tier, not on every tick.
  const bucketKey = useTrafficStore(
    (s) => roadEdges.map((e) => getBucket(s.roadCongestion[e.id])).join(","),
  );
  // The order on screen is held until the operator asks for a re-sort: rows
  // never move under the pointer (the source of the page's layout shift).
  // The first real data sorts automatically, since nothing is shown yet.
  const [shown, setShown] = useState(() => ({ key: bucketKey, order: sortRoads(bucketKey) }));
  const noData = !shown.key.split(",").some((b) => b !== "3");
  useEffect(() => {
    if (noData && bucketKey !== shown.key) setShown({ key: bucketKey, order: sortRoads(bucketKey) });
  }, [noData, bucketKey, shown.key]);
  const changed = useMemo(() => {
    if (bucketKey === shown.key) return 0;
    const now = bucketKey.split(",");
    return shown.key.split(",").filter((b, i) => b !== now[i]).length;
  }, [bucketKey, shown.key]);
  const resort = () => setShown({ key: bucketKey, order: sortRoads(bucketKey) });

  const roads = shown.order.filter((e) =>
    `${e.name ?? "Unnamed road"} ${e.id}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <section className="product-panel road-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">NETWORK CONDITIONS</span>
          <h2>Road intelligence</h2>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setFrozen(frozen ? null : liveCongestion)}
            aria-pressed={frozen !== null}
            aria-label={frozen ? "Resume live road updates" : "Pause live road updates"}
            title={frozen ? "Resume live updates" : "Pause live updates"}
            className="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {frozen ? <Play size={15} /> : <Pause size={15} />}
          </button>
          <Route size={18} className="text-primary" />
        </div>
      </div>
      {!compact && (
        <label className="road-search">
          <Search size={15} />
          <input
            aria-label="Search roads"
            placeholder="Search road name or edge ID"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      )}
      <div className="road-list">
        {/* Zero-height sticky slot: the pill floats over the rows instead of
            pushing them down, so offering a re-sort causes no layout shift. */}
        <div className="pointer-events-none sticky top-2 z-10 flex h-0 justify-center">
          {changed > 0 && !frozen && (
            <button
              type="button"
              onClick={resort}
              className="pointer-events-auto flex h-8 animate-fade-in items-center gap-1.5 rounded-full bg-primary px-3 text-xs font-medium text-primary-foreground shadow-elevation-2"
            >
              <RefreshCw size={13} />
              {changed} {changed === 1 ? "road" : "roads"} changed · Re-sort
            </button>
          )}
        </div>
        {(compact ? roads.slice(0, 4) : roads).map((e) => {
          const value = congestion[e.id];
          const tone =
            value == null
              ? "muted"
              : value > 0.6
                ? "critical"
                : value > 0.35
                  ? "warn"
                  : "ok";
          const mid = e.path[Math.floor(e.path.length / 2)];
          return (
            <button
              key={e.id}
              className="road-row"
              onClick={() =>
                focusOn({ longitude: mid[0], latitude: mid[1] }, 16)
              }
              title={`Focus road ${e.id} on map`}
            >
              <span className={`road-status ${tone}`} />
              <span className="min-w-0 flex-1">
                <strong>{e.name || `Road ${e.id}`}</strong>
                <small>
                  {e.numLanes} {e.numLanes === 1 ? "lane" : "lanes"} ·{" "}
                  {(e.lengthM / 1000).toFixed(2)} km
                </small>
              </span>
              <span className="road-load">
                <b>{value == null ? "—" : `${Math.round(value * 100)}%`}</b>
                <small>{value == null ? "No data" : "occupancy"}</small>
              </span>
              <ArrowUpRight size={14} />
            </button>
          );
        })}
        {roads.length === 0 && (
          <p className="empty-copy">
            No matching roads. Try a name or SUMO edge ID.
          </p>
        )}
      </div>
    </section>
  );
}

export function SignalHealth() {
  const intersections = useIncidentStore((s) => s.intersections);
  const focusOn = useMapStore((s) => s.focusOn);
  const select = useIncidentStore((s) => s.selectIntersection);
  const demo = useSystemStore((s) => s.dataMode === "simulation");
  return (
    <section className="product-panel signal-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">JUNCTION OBSERVATIONS</span>
          <h2>Signal network</h2>
        </div>
        <RadioTower size={18} className="text-primary" />
      </div>
      <div className="signal-grid">
        {intersections.map((j) => (
          <button
            key={j.id}
            onClick={() => {
              select(j.id);
              focusOn(j, 17);
            }}
            title={`${j.name}: ${j.fault ? j.fault.detail : j.preempted ? "Emergency preemption" : demo ? "Demo phase" : "Controller activity, not lamp state"}`}
          >
            <span
              className={`signal-lamp ${j.fault ? "fault" : j.preempted ? "preempted" : j.signalState}`}
            />
            <strong>{j.name}</strong>
            <small>
              {j.fault
                ? "Fault"
                : j.preempted
                  ? "Preempted"
                  : demo
                    ? j.signalState
                    : j.signalState === "green"
                      ? "Reporting"
                      : "No signal"}
            </small>
          </button>
        ))}
      </div>
      {!intersections.length && (
        <p className="empty-copy">
          <MapPin size={18} /> Awaiting junction observations.
        </p>
      )}
      <p className="panel-footnote">
        {demo
          ? "Illustrative phases · browser demo"
          : "Controller liveness, not individual lamp phases"}
      </p>
    </section>
  );
}
