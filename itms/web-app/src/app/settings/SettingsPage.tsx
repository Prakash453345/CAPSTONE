import { FlaskConical, Radio } from "lucide-react";
import { useSystemStore } from "@/store/systemStore";
import { useMapStore, type MapLayerId } from "@/store/mapStore";
import { cn } from "@/utils/cn";
import type { DataMode } from "@/types";

const LAYER_LABELS: Record<MapLayerId, string> = {
  vehicles: "Vehicles",
  signals: "Signals",
  congestion: "Congestion",
  incidents: "Incidents",
  anomalies: "Anomalies",
  emergency: "Emergency routes & units",
  weather: "Weather",
};

/**
 * Operator preferences that live entirely client-side: which data source to
 * read and which map layers are on by default. Detection/routing thresholds are
 * governed server-side (`EmergencyRoutingConfig`, Tier-0 config) and are not
 * editable here.
 */
export function SettingsPage() {
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  const activeLayers = useMapStore((s) => s.activeLayers);
  const toggleLayer = useMapStore((s) => s.toggleLayer);

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <header>
        <h2 className="text-base font-semibold tracking-tight">Settings</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Your workspace, your view. Changes apply immediately for this session.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">Data source</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Live reads the running command-driven simulation over WebSocket. Simulation
          runs a self-contained mock — no backend required.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {(
            [
              ["live", "Live", Radio, "api-service WebSocket"],
              ["simulation", "Simulation", FlaskConical, "in-browser mock"],
            ] as [DataMode, string, typeof Radio, string][]
          ).map(([value, label, Icon, hint]) => (
            <button
              key={value}
              type="button"
              onClick={() => setDataMode(value)}
              className={cn(
                "rounded-md border px-3 py-2.5 text-left transition-colors",
                dataMode === value
                  ? "border-primary/70 bg-primary/10"
                  : "border-border hover:bg-muted",
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <Icon className="size-3.5" /> {label}
              </span>
              <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                {hint}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">Map layers</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Which overlays are drawn on every map in the app.
        </p>
        <ul className="mt-3 divide-y divide-border/60">
          {(Object.keys(LAYER_LABELS) as MapLayerId[]).map((id) => {
            const on = activeLayers.has(id);
            return (
              <li key={id} className="flex items-center justify-between py-2">
                <span className="text-sm">{LAYER_LABELS[id]}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={LAYER_LABELS[id]}
                  onClick={() => toggleLayer(id)}
                  className={cn(
                    "flex h-5 w-9 items-center rounded-full border border-border p-0.5 transition-colors",
                    on ? "justify-end bg-primary/70" : "justify-start bg-muted",
                  )}
                >
                  <span className="size-3.5 rounded-full bg-foreground" />
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="product-panel p-5"><span className="eyebrow">PLATFORM CAPABILITIES</span><h3 className="mt-2 text-sm font-semibold">Know what is behind the numbers.</h3><dl className="mt-4 space-y-4 text-xs leading-relaxed"><div><dt className="font-medium text-primary">Live simulation & safety arbitration</dt><dd className="mt-1 text-muted-foreground">SUMO traffic, controller activity, disruption commands, emergency routes and green-corridor reservations. All signal proposals pass the backend safety interlocks.</dd></div><div><dt className="font-medium text-status-warn">Detection needs a trained model</dt><dd className="mt-1 text-muted-foreground">M6 graph/conformal detection is integrated, but model readiness and accuracy are not guaranteed. Incident candidates require human review. Camera / vision ingestion is not implemented.</dd></div><div><dt className="font-medium">Session analytics, not historical claims</dt><dd className="mt-1 text-muted-foreground">Charts contain up to 30 minutes of received observations. Refreshing or changing sources resets them. Benchmark comparisons remain in the backend harness.</dd></div></dl></section>
      <p className="text-[11px] text-muted-foreground">
        Detection thresholds, routing weights and signal timing (min-green, clearance,
        preemption budget) are server-side safety configuration and are not editable from
        the console.
      </p>
    </div>
  );
}
