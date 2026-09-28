import { useState } from "react";
import { Download, ChartNoAxesCombined, Info } from "lucide-react";
import { TelemetryChart } from "@/components/panels/TelemetryChart";
import { DataFreshness } from "@/components/layout/DataFreshness";
import { useAnalyticsStore, telemetryCsv } from "@/store/analyticsStore";
import { useSystemStore } from "@/store/systemStore";

export function AnalyticsPage() {
  const history = useAnalyticsStore((s) => s.samples);
  const mode = useSystemStore((s) => s.dataMode);
  const [minutes, setMinutes] = useState(5);
  const end = history[history.length - 1]?.at ?? 0;
  const samples = history.filter((s) => s.at >= end - minutes * 60_000);
  const latest = samples[samples.length - 1];
  const exportCsv = () => {
    const url = URL.createObjectURL(
      new Blob([telemetryCsv(samples)], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `traffix-${mode}-session-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const charts = [
    {
      label: "Network congestion",
      value: latest ? `${latest.congestion.toFixed(1)}%` : "—",
      values: samples.map((s) => s.congestion),
      color: "#edba70",
      max: 100,
      hint: "Mean road occupancy across reported edges",
    },
    {
      label: "Mean vehicle speed",
      value: latest?.speed == null ? "—" : `${latest.speed.toFixed(1)} km/h`,
      values: samples.map((s) => s.speed),
      color: "#72e5be",
      hint: "Observed vehicles, not a corridor travel-time estimate",
    },
    {
      label: "Vehicles on network",
      value: latest?.vehicles ?? "—",
      values: samples.map((s) => s.vehicles),
      color: "#8dafff",
      hint: "Simultaneously observed vehicles, not throughput",
    },
    {
      label: "Signals reporting",
      value: latest?.signals ?? "—",
      values: samples.map((s) => s.signals),
      color: "#b4a3ef",
      hint: "Recent signal-controller activity",
    },
  ];
  return (
    <div className="overview-page analytics-page">
      <header className="overview-heading">
        <div>
          <div className="eyebrow">OBSERVE / UNDERSTAND / ACT</div>
          <h1>
            Patterns in <span>motion.</span>
          </h1>
          <p>Clearer decisions start with a clearer picture.</p>
        </div>
        <button
          className="primary-action"
          disabled={!samples.length}
          onClick={exportCsv}
        >
          <Download size={16} /> Export observations
        </button>
      </header>
      <div className="analytics-toolbar">
        <div
          className="flex gap-1"
          role="group"
          aria-label="Observation window"
        >
          {[1, 5, 15, 30].map((m) => (
            <button
              key={m}
              aria-pressed={minutes === m}
              className={`window-button ${minutes === m ? "active" : ""}`}
              onClick={() => setMinutes(m)}
            >
              {m} min
            </button>
          ))}
        </div>
        <DataFreshness />
      </div>
      <div className="analytics-notice">
        <Info size={17} />
        <span>
          {mode === "simulation"
            ? "Browser demo observations"
            : "Live session observations"}{" "}
          · {samples.length} samples. Up to 30 minutes kept in memory; changing
          data source starts a new session. No historical or benchmark data is
          implied.
        </span>
      </div>
      <div className="analytics-grid">
        {charts.map((chart) => (
          <section key={chart.label} className="product-panel analytics-chart">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">{chart.label}</span>
                <h2 className="analytics-value">{chart.value}</h2>
              </div>
              <ChartNoAxesCombined size={20} style={{ color: chart.color }} />
            </div>
            <TelemetryChart
              values={chart.values}
              label={`${chart.label} over the selected ${minutes}-minute session window`}
              height={180}
              color={chart.color}
              max={chart.max}
            />
            <div className="chart-axis">
              <span>
                {samples[0]
                  ? new Date(samples[0].at).toLocaleTimeString()
                  : "Awaiting data"}
              </span>
              <span>Latest observation</span>
            </div>
            <p className="panel-footnote">{chart.hint}</p>
          </section>
        ))}
      </div>
      <section className="product-panel mt-5 p-5">
        <h2 className="text-sm font-semibold">Beyond this session</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Person-delay, completed-trip throughput and statistically paired
          controller comparisons are calculated by the backend benchmark
          harness. A historical analytics API is not available yet. Incident
          detection accuracy is not inferred from these charts.
        </p>
      </section>
    </div>
  );
}
