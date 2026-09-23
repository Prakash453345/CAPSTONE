import { Link, useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  ArrowRight,
  Car,
  Gauge,
  RadioTower,
  Siren,
  MapPin,
  ScanEye,
  Activity,
  ShieldCheck,
} from "lucide-react";
import { TrafficMap } from "@/components/map/TrafficMap";
import { ActivityFeed } from "@/components/panels/ActivityFeed";
import {
  RoadConditions,
  SignalHealth,
} from "@/components/panels/NetworkPanels";
import { TelemetryChart } from "@/components/panels/TelemetryChart";
import { DataFreshness } from "@/components/layout/DataFreshness";
import { useSystemStore } from "@/store/systemStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useAnalyticsStore } from "@/store/analyticsStore";
import { useActiveRequests, useEmergencyStore } from "@/store/emergencyStore";
import { roadEdges, signalJunctions } from "@/data/network";

export function DashboardPage() {
  const navigate = useNavigate();
  const summary = useSystemStore((s) => s.summary);
  const demo = useSystemStore((s) => s.dataMode === "simulation");
  const samples = useAnalyticsStore((s) => s.samples);
  const incidents = useIncidentStore((s) => s.incidents);
  const anomalies = useIncidentStore((s) => s.anomalies);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const active = useActiveRequests();
  const pending = incidents.filter((i) => i.status === "candidate");
  const disruptions = anomalies.filter((a) => a.status === "active");
  const latest = samples[samples.length - 1];
  const available = summary.lastUpdate !== null;
  const mission = active[0];
  const metrics = [
    {
      label: "Vehicles on network",
      value: available ? summary.vehicleCount.toLocaleString() : "—",
      unit: "",
      icon: Car,
      note: "Observed across the corridor",
      values: samples.map((s) => s.vehicles),
      color: "#72e5be",
    },
    {
      label: "Average speed",
      value: latest?.speed == null ? "—" : latest.speed.toFixed(1),
      unit: "km/h",
      icon: Gauge,
      note: "Mean of observed vehicles",
      values: samples.map((s) => s.speed),
      color: "#8dafff",
    },
    {
      label: "Network congestion",
      value: available ? Math.round(summary.congestion * 100) : "—",
      unit: "%",
      icon: Activity,
      note: "Mean reported road occupancy",
      values: samples.map((s) => s.congestion),
      color: "#edba70",
    },
    {
      label: "Signals reporting",
      value: available ? summary.signalsOnline : "—",
      unit: `/ ${signalJunctions.length}`,
      icon: RadioTower,
      note: demo ? "Illustrative signal cycle" : "Recent controller activity",
      values: samples.map((s) => s.signals),
      color: "#b4a3ef",
    },
  ];
  return (
    <div className="overview-page">
      <header className="overview-heading">
        <div>
          <div className="eyebrow">
            <span className="tiny-square" /> URBAN INTELLIGENCE / VIJAYAWADA
          </div>
          <h1>
            A city in motion.<span> In view.</span>
          </h1>
          <p>Your network, understood. Your next move, informed.</p>
        </div>
        <Link className="primary-action" to="/emergency">
          <Siren size={16} /> Emergency response <ArrowUpRight size={16} />
        </Link>
      </header>
      <div className="overview-context">
        <span>
          <MapPin size={13} /> MG Road corridor <i /> {roadEdges.length} road
          segments
        </span>
        <DataFreshness />
      </div>
      <div className="metric-grid">
        {metrics.map((m) => (
          <section className="metric-card" key={m.label}>
            <div className="metric-label">
              {m.label}
              <m.icon size={17} style={{ color: m.color }} />
            </div>
            <div className="metric-value">
              {m.value}
              <span>{m.unit}</span>
            </div>
            <div className="metric-chart">
              <TelemetryChart
                values={m.values.slice(-60)}
                label={`${m.label}, recent session observations`}
                height={44}
                color={m.color}
              />
            </div>
            <p>{m.note}</p>
          </section>
        ))}
      </div>
      <div className="command-grid">
        <section className="product-panel overview-map">
          <div className="panel-heading">
            <div className="flex items-center gap-3">
              <span className="map-heading-icon">
                <MapPin size={17} />
              </span>
              <div>
                <h2>Network live view</h2>
                <p>Vijayawada, Andhra Pradesh</p>
              </div>
            </div>
            <Link className="text-action" to="/traffic">
              Explore map <ArrowUpRight size={15} />
            </Link>
          </div>
          <div className="overview-map-canvas">
            <TrafficMap />
          </div>
          <div className="map-caption">
            <span>
              <span className="telemetry-pulse" />{" "}
              {demo ? "DEMO NETWORK" : "SUMO / LIVE STREAM"}
            </span>
            <span>Geographic road network · OpenStreetMap</span>
          </div>
        </section>
        <aside className="overview-right">
          <section className="product-panel attention-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">OPERATOR INBOX</span>
                <h2>Needs attention</h2>
              </div>
              <ScanEye size={19} className="text-status-warn" />
            </div>
            <Link to="/anomalies" className="attention-row">
              <span className="attention-count">
                {pending.length.toString().padStart(2, "0")}
              </span>
              <span>
                Incident candidates<small>Awaiting human review</small>
              </span>
              <ArrowUpRight size={16} />
            </Link>
            <Link to="/anomalies" className="attention-row">
              <span className="attention-count muted-count">
                {disruptions.length.toString().padStart(2, "0")}
              </span>
              <span>
                Active disruptions<small>Operator & detector reports</small>
              </span>
              <ArrowUpRight size={16} />
            </Link>
            <div className="inbox-note">
              <ShieldCheck size={14} />{" "}
              {demo
                ? "Illustrative incidents · no live actions"
                : "Human confirmation before incident escalation"}
            </div>
          </section>
          <section className="product-panel mission-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">PRIORITY MOVEMENT</span>
                <h2>Emergency operations</h2>
              </div>
              <Siren size={18} className="text-primary" />
            </div>
            {mission ? (
              <>
                <div className="mission-summary">
                  <span className="mission-icon">
                    <Siren size={22} />
                  </span>
                  <div>
                    <strong>{mission.vehicleId}</strong>
                    <small>{mission.state.replace(/_/g, " ")}</small>
                  </div>
                  <span className="mission-eta">
                    {mission.etaS == null ? "—" : Math.ceil(mission.etaS / 60)}
                    <small>min ETA</small>
                  </span>
                </div>
                <div className="mission-track">
                  <span
                    style={{
                      width: `${(mission.live?.routeProgress ?? 0) * 100}%`,
                    }}
                  />
                </div>
                <div className="mission-detail">
                  <span>
                    {mission.corridor?.status === "active"
                      ? "Green corridor active"
                      : "Route monitoring"}
                  </span>
                  <span>
                    {Math.round((mission.live?.routeProgress ?? 0) * 100)}%
                    complete
                  </span>
                </div>
                <button
                  className="mission-button"
                  onClick={() => {
                    selectRequest(mission.id);
                    navigate("/emergency");
                  }}
                >
                  Track mission <ArrowRight size={15} />
                </button>
              </>
            ) : (
              <div className="empty-copy">
                <ShieldCheck size={24} />
                <strong>No active missions</strong>
                <span>
                  Dispatch a unit to plan a route and prepare a green corridor.
                </span>
                <Link className="text-action" to="/emergency">
                  Open emergency workspace <ArrowRight size={14} />
                </Link>
              </div>
            )}
          </section>
        </aside>
      </div>
      <div className="overview-bottom">
        <RoadConditions compact />
        <SignalHealth />
        <section className="product-panel activity-panel">
          <ActivityFeed className="h-full" />
        </section>
      </div>
      <footer className="overview-footer">
        <span>
          TRAFFIX <i /> INTELLIGENT TRAFFIC MANAGEMENT
        </span>
        <Link to="/analytics">
          Explore session analytics <ArrowUpRight size={13} />
        </Link>
      </footer>
    </div>
  );
}
