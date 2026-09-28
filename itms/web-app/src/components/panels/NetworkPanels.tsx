import { useState } from "react";
import { ArrowUpRight, Search, RadioTower, Route, MapPin } from "lucide-react";
import { roadEdges } from "@/data/network";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";

export function RoadConditions({ compact = false }: { compact?: boolean }) {
  const congestion = useTrafficStore((s) => s.roadCongestion);
  const focusOn = useMapStore((s) => s.focusOn);
  const [search, setSearch] = useState("");
  const roads = roadEdges
    .filter((e) =>
      `${e.name ?? "Unnamed road"} ${e.id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    )
    .sort((a, b) => (congestion[b.id] ?? -1) - (congestion[a.id] ?? -1));
  return (
    <section className="product-panel road-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">NETWORK CONDITIONS</span>
          <h2>Road intelligence</h2>
        </div>
        <Route size={18} className="text-primary" />
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
