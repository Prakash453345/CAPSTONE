import { useRef, useState } from "react";
import { ChevronDown, Columns2, FlaskConical, Radio, Square } from "lucide-react";
import { useSystemStore, selectIsStale } from "@/store/systemStore";
import { networkName, roadEdges, signalJunctions } from "@/data/network";
import { Dot, Popover, Segmented } from "@/components/console/kit";
import { ago, useNow } from "@/components/console/hooks";
import { type Tone } from "@/components/console/tone";
import { cn } from "@/utils/cn";
import type { DataMode, ViewMode } from "@/types";

/**
 * One chip that answers "can I trust what I'm seeing?", replacing a row of
 * separate mode, connection, clock and layout controls. The popover holds the
 * detail and the switches.
 */
export function StatusMenu() {
  const now = useNow();
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  const status = useSystemStore((s) => s.connectionStatus);
  const lastUpdate = useSystemStore((s) => s.summary.lastUpdate);
  const stale = useSystemStore((s) => selectIsStale(s, now));
  const viewMode = useSystemStore((s) => s.viewMode);
  const setViewMode = useSystemStore((s) => s.setViewMode);

  const demo = dataMode === "simulation";
  const state: { label: string; tone: Tone; detail: string } = demo
    ? { label: "Demo data", tone: "warn", detail: "Illustrative browser simulation" }
    : status === "online" && stale
      ? { label: "Stale data", tone: "warn", detail: "Connected, but updates have paused" }
      : status === "online"
        ? { label: "Live", tone: "ok", detail: "Streaming from the city simulation" }
        : status === "offline"
          ? { label: "Offline", tone: "critical", detail: "No connection to the live stream" }
          : { label: "Connecting", tone: "info", detail: "Waiting for the live stream" };

  const updated = lastUpdate ? `Updated ${ago(Date.parse(lastUpdate), now)}` : "Awaiting telemetry";

  return (
    <div className="relative">
      <button
        ref={anchor}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`${state.label}, ${updated}. Data and connection`}
        className={cn(
          "flex h-9 items-center gap-2 rounded-xl px-3 text-[13px] font-medium text-foreground transition-colors hover:bg-muted",
          open && "bg-muted",
        )}
      >
        <Dot tone={state.tone} pulse={state.tone === "ok" || state.tone === "info"} />
        <span className="hidden sm:inline">{state.label}</span>
        <span className="hidden text-muted-foreground xl:inline">· {updated}</span>
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform duration-200", open && "rotate-180")} />
      </button>

      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label="Data and connection" className="w-[340px]">
        <div className="px-3 pb-3 pt-2">
          <div className="flex items-center gap-2.5">
            <Dot tone={state.tone} pulse={state.tone === "ok"} />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground">{state.label}</p>
              <p className="text-[12.5px] text-muted-foreground">{state.detail}</p>
            </div>
          </div>
          {demo && (
            <p className="mt-3 rounded-xl bg-status-warn-muted px-3 py-2.5 text-[12.5px] leading-relaxed text-status-warn">
              Demo environment. Illustrative browser simulation, not live city traffic. Reports and dispatches work, but nothing leaves this browser.
            </p>
          )}
          {!demo && status !== "online" && (
            <p className="mt-3 rounded-xl bg-muted px-3 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
              Start api-service and SUMO; the stream reconnects on its own. You can explore the demo meanwhile.
            </p>
          )}
        </div>

        <div className="space-y-3 border-t border-border px-3 py-3">
          <Row label="Data source">
            <Segmented<DataMode>
              size="sm"
              value={dataMode}
              onChange={setDataMode}
              ariaLabel="Data source"
              options={[
                { value: "live", label: "Live", icon: Radio },
                { value: "simulation", label: "Demo", icon: FlaskConical },
              ]}
            />
          </Row>
          <Row label="Layout">
            <Segmented<ViewMode>
              size="sm"
              value={viewMode}
              onChange={(v) => {
                setViewMode(v);
                setOpen(false);
              }}
              ariaLabel="Layout"
              options={[
                { value: "single", label: "Single", icon: Square },
                { value: "split", label: "Split", icon: Columns2 },
              ]}
            />
          </Row>
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-border px-3 pb-2 pt-3 text-[12.5px]">
          <Fact term="Last update" value={updated.replace("Updated ", "")} />
          <Fact term="Local time" value={new Date(now).toLocaleTimeString("en-GB")} />
          <Fact term="Network" value={networkName} />
          <Fact term="Coverage" value={`${roadEdges.length} roads, ${signalJunctions.length} signals`} />
        </dl>
      </Popover>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="mt-0.5 font-medium text-foreground tabular">{value}</dd>
    </div>
  );
}
