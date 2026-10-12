import { useState } from "react";
import { motion } from "framer-motion";
import { Download, Info } from "lucide-react";
import { AreaChart } from "@/components/console/AreaChart";
import { AnimatedNumber, Button, PageHeader, Panel, PanelHeader, Segmented } from "@/components/console/kit";
import { EASE_OUT } from "@/components/console/motion";
import { useAnalyticsStore, telemetryCsv, type TelemetrySample } from "@/store/analyticsStore";
import { useSystemStore } from "@/store/systemStore";

type Window = "1" | "5" | "15" | "30";

function mean(xs: (number | null)[]) {
  const v = xs.filter((x): x is number => x !== null && Number.isFinite(x));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

/**
 * Session analytics: what the network has done since the console opened.
 * Charts show observations only; nothing is extrapolated or benchmarked.
 */
export function AnalyticsPage() {
  const history = useAnalyticsStore((s) => s.samples);
  const mode = useSystemStore((s) => s.dataMode);
  const [win, setWin] = useState<Window>("5");
  const minutes = Number(win);
  const end = history[history.length - 1]?.at ?? 0;
  const samples = history.filter((s) => s.at >= end - minutes * 60_000);

  const exportCsv = () => {
    const url = URL.createObjectURL(new Blob([telemetryCsv(samples)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `traffix-${mode}-session-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const series = (pick: (s: TelemetrySample) => number | null) => samples.map((s) => ({ at: s.at, value: pick(s) }));
  const peakVehicles = samples.length ? Math.max(...samples.map((s) => s.vehicles)) : null;

  const charts = [
    { title: "Congestion", sub: "Mean road occupancy across reported roads", color: "#e8a33d", max: 100, points: series((s) => s.congestion), format: (v: number) => `${v.toFixed(0)}%` },
    { title: "Average speed", sub: "Of observed vehicles, not a travel-time estimate", color: "#34c3a0", points: series((s) => s.speed), format: (v: number) => `${v.toFixed(0)} km/h` },
    { title: "Vehicles on the network", sub: "Seen at the same moment, not throughput", color: "#6f8fff", points: series((s) => s.vehicles), format: (v: number) => v.toFixed(0) },
    { title: "Signals reporting", sub: "Controllers with recent activity", color: "#a78bfa", points: series((s) => s.signals), format: (v: number) => v.toFixed(0) },
  ];

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-4 pb-8 sm:px-6">
      <PageHeader
        title="Session analytics"
        description={`What the corridor has done since you opened the console. ${samples.length} observations in view.`}
        actions={
          <>
            <Segmented<Window>
              value={win}
              onChange={setWin}
              ariaLabel="Observation window"
              options={[
                { value: "1", label: "1 min" },
                { value: "5", label: "5 min" },
                { value: "15", label: "15 min" },
                { value: "30", label: "30 min" },
              ]}
            />
            <Button icon={Download} disabled={!samples.length} onClick={exportCsv}>
              Export observations
            </Button>
          </>
        }
      />

      <Panel className="grid grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Average congestion", value: mean(samples.map((s) => s.congestion)), unit: "%", fmt: (v: number) => v.toFixed(1) },
          { label: "Average speed", value: mean(samples.map((s) => s.speed)), unit: "km/h", fmt: (v: number) => v.toFixed(1) },
          { label: "Peak vehicles", value: peakVehicles, unit: "", fmt: (v: number) => Math.round(v).toString() },
          { label: "Disruptions seen", value: samples.length ? Math.max(...samples.map((s) => s.anomalies)) : null, unit: "at once, at most", fmt: (v: number) => Math.round(v).toString() },
        ].map((s, i) => (
          <div key={s.label} className={i ? "border-l border-border px-5 py-4 max-lg:[&:nth-child(3)]:border-l-0 max-lg:[&:nth-child(n+3)]:border-t" : "px-5 py-4"}>
            <p className="text-[12.5px] text-muted-foreground">{s.label}</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <AnimatedNumber value={s.value} format={s.fmt} className="text-[24px] font-semibold tracking-[-0.02em] text-foreground" />
              <span className="text-[13px] text-muted-foreground">{s.unit}</span>
            </p>
          </div>
        ))}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        {charts.map((c, i) => (
          <motion.div key={c.title} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.05 * i, ease: EASE_OUT }}>
            <Panel>
              <PanelHeader title={c.title} subtitle={c.sub} />
              <div className="px-4 pb-4">
                <AreaChart points={c.points} color={c.color} max={c.max} format={c.format} label={`${c.title} over the last ${minutes} minutes`} />
              </div>
            </Panel>
          </motion.div>
        ))}
      </div>

      <p className="flex items-start gap-2 text-[12.5px] leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" />
        {mode === "simulation" ? "Demo observations from the browser simulation." : "Observations from the live session."} Up to 30 minutes are kept in
        memory and changing the data source starts over. Person-delay, throughput and controller comparisons come from the backend benchmark
        harness, not from these charts.
      </p>
    </div>
  );
}
