import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Columns2, Loader2, MapPin, Plus, TrafficCone, TriangleAlert } from "lucide-react";
import { IncidentInbox } from "@/components/panels/IncidentInbox";
import { ClipReview } from "@/components/panels/ClipReview";
import { needsReview, useClipStore } from "@/store/clipStore";
import { TrafficMap } from "@/components/map/TrafficMap";
import { WorkspaceLayout } from "@/components/console/WorkspaceLayout";
import { Button, EmptyState, Meter, Pill, Segmented } from "@/components/console/kit";
import { EASE_OUT, listMotion } from "@/components/console/motion";
import { ago, useNow } from "@/components/console/hooks";
import { toneBg, toneText, type Tone } from "@/components/console/tone";
import { anomalyWord, SOURCE_WORDS } from "@/components/console/words";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";
import { edgeById, roadLabel } from "@/data/network";
import { cn } from "@/utils/cn";
import { CommandError, postCommand } from "@/services/traffic/commands";
import type { Anomaly } from "@/types";

type Tab = "review" | "active" | "resolved";

const SEVERITY: Record<Anomaly["severity"], { word: string; tone: Tone }> = {
  low: { word: "Minor", tone: "warn" },
  medium: { word: "Moderate", tone: "warn" },
  high: { word: "Serious", tone: "critical" },
  blocked: { word: "Road blocked", tone: "critical" },
};

function focusEdge(edgeId: string, zoom = 16.5) {
  const e = edgeById.get(edgeId);
  if (!e) return;
  const mid = e.path[Math.floor(e.path.length / 2)]!;
  useMapStore.getState().focusOn({ longitude: mid[0], latitude: mid[1] }, zoom);
}

/**
 * Incidents: what the detector wants a person to check, what is disrupting
 * the road right now, and what has been cleared.
 */
export function AnomaliesPage() {
  const anomalies = useIncidentStore((s) => s.anomalies);
  const detectorCandidates = useIncidentStore((s) => s.incidents.filter((i) => i.status === "candidate").length);
  const clipFindings = useClipStore((s) => s.clips.filter(needsReview).length);
  const candidates = detectorCandidates + clipFindings;
  const selectedId = useIncidentStore((s) => s.selectedAnomalyId);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const creating = useMapStore((s) => s.interactionMode === "create-anomaly");
  const setViewMode = useSystemStore((s) => s.setViewMode);
  const now = useNow(15_000);

  const active = anomalies.filter((a) => a.status === "active");
  const done = anomalies.filter((a) => a.status !== "active");
  const [tab, setTab] = useState<Tab>(() => (active.length && !candidates ? "active" : "review"));

  const byTime = (a: Anomaly, b: Anomaly) => (Date.parse(b.startTime) || 0) - (Date.parse(a.startTime) || 0);
  const list = (tab === "active" ? active : done).sort(byTime);

  const panel = (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div>
          <h2 className="text-[15px] font-semibold text-foreground">Road disruptions</h2>
          <p className="text-[13px] text-muted-foreground">
            {active.length} on the road · {candidates} to review
          </p>
        </div>
        <Button
          variant={creating ? "secondary" : "primary"}
          size="sm"
          icon={creating ? undefined : Plus}
          onClick={() => setInteractionMode(creating ? "idle" : "create-anomaly")}
        >
          {creating ? "Cancel" : "Report"}
        </Button>
      </header>
      <AnimatePresence>
        {creating && (
          <motion.p
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mx-5 mb-3 overflow-hidden rounded-xl bg-primary-muted px-3.5 py-2.5 text-[13px] text-primary"
          >
            Click the road on the map where the disruption is.
          </motion.p>
        )}
      </AnimatePresence>
      <div className="px-4 pb-3">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          ariaLabel="Show"
          className="w-full"
          size="sm"
          options={[
            { value: "review", label: `To review${candidates ? ` (${candidates})` : ""}` },
            { value: "active", label: `On the road${active.length ? ` (${active.length})` : ""}` },
            { value: "resolved", label: "Resolved" },
          ]}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2, ease: EASE_OUT }}>
            {tab === "review" ? (
              <>
                <ClipReview />
                <IncidentInbox />
              </>
            ) : list.length === 0 ? (
              tab === "active" ? (
                <EmptyState
                  icon={CheckCircle2}
                  title="The road is clear"
                  body="No disruptions right now. Report one if you see it before the detector does."
                  action={
                    <Button icon={Plus} onClick={() => setInteractionMode("create-anomaly")}>
                      Report a disruption
                    </Button>
                  }
                />
              ) : (
                <EmptyState icon={TrafficCone} title="Nothing resolved yet" body="Cleared disruptions collect here for the session." />
              )
            ) : (
              <motion.ul variants={listMotion.container} initial="hidden" animate="show" className="space-y-2">
                {list.map((a) => {
                  const sev = SEVERITY[a.severity];
                  const sel = a.id === selectedId;
                  const live = a.status === "active";
                  return (
                    <motion.li
                      key={a.id}
                      variants={listMotion.item}
                      className={cn("rounded-2xl bg-surface p-3.5 shadow-elevation-1 transition-shadow", sel && "ring-2 ring-primary/40", !live && "opacity-70")}
                    >
                      <button
                        type="button"
                        className="flex w-full items-start gap-3 text-left"
                        onClick={() => {
                          selectAnomaly(sel ? null : a.id);
                          focusEdge(a.edgeId);
                        }}
                      >
                        <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", toneBg(sev.tone), toneText(sev.tone))}>
                          {a.severity === "blocked" ? <TrafficCone size={17} /> : <TriangleAlert size={17} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center justify-between gap-2">
                            <span className="truncate text-[13.5px] font-medium text-foreground">
                              {anomalyWord(a.kind)} on {roadLabel(a.edgeId)}
                            </span>
                            <Pill tone={live ? sev.tone : "neutral"}>{live ? sev.word : a.status === "resolved" ? "Resolved" : "Cancelled"}</Pill>
                          </span>
                          <span className="mt-0.5 block text-[12.5px] text-muted-foreground">
                            {SOURCE_WORDS[a.source] ?? a.source} · {ago(Date.parse(a.startTime), now)}
                          </span>
                          {a.detail && <span className="mt-1 block text-[12.5px] text-foreground/80">{a.detail}</span>}
                          <span className="mt-2.5 flex items-center gap-2 text-[12px] text-muted-foreground">
                            <Meter value={a.estimatedImpact} tone={sev.tone} className="flex-1" />
                            {Math.round(a.estimatedImpact * 100)}% capacity lost
                          </span>
                        </span>
                      </button>
                      {live && (
                        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
                          <Button variant="ghost" size="sm" icon={MapPin} onClick={() => focusEdge(a.edgeId, 17)}>
                            Show on map
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={Columns2}
                            onClick={() => {
                              focusEdge(a.edgeId, 16);
                              setViewMode("split");
                            }}
                          >
                            Compare traffic
                          </Button>
                          <ClearAnomalyControl anomaly={a} />
                        </div>
                      )}
                    </motion.li>
                  );
                })}
              </motion.ul>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );

  return <WorkspaceLayout label="Incidents" panel={panel} map={<TrafficMap />} />;
}

/**
 * Manual clear for an active anomaly: the operator says whether it genuinely
 * ended or was reported in error, matching the two meanings of
 * `AnomalyClearRequested`. Always two steps; a failed request shows inline.
 */
function ClearAnomalyControl({ anomaly }: { anomaly: Anomaly }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<null | "RESOLVED" | "CANCELLED">(null);
  const [error, setError] = useState<string | null>(null);

  const clear = async (resolution: "RESOLVED" | "CANCELLED") => {
    setBusy(resolution);
    setError(null);
    try {
      await postCommand({
        event_type: "AnomalyClearRequested",
        payload: {
          anomaly_id: anomaly.id,
          resolution,
          reason: resolution === "CANCELLED" ? "reported in error" : "",
          requested_at: Date.now(),
        },
      });
      setConfirming(false);
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Backend unreachable. Is the live simulation running?"
            : err.detail
          : "Could not clear the anomaly.",
      );
    } finally {
      setBusy(null);
    }
  };

  if (!confirming)
    return (
      <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setConfirming(true)}>
        Clear
      </Button>
    );

  return (
    <div className="mt-1 w-full space-y-2">
      <p className="text-[12.5px] text-muted-foreground">How did it end?</p>
      <div className="flex gap-2">
        <Button size="sm" className="flex-1" onClick={() => clear("RESOLVED")} disabled={busy != null}>
          {busy === "RESOLVED" && <Loader2 className="size-3.5 animate-spin" />}
          It's resolved
        </Button>
        <Button size="sm" variant="ghost" className="flex-1" onClick={() => clear("CANCELLED")} disabled={busy != null}>
          {busy === "CANCELLED" && <Loader2 className="size-3.5 animate-spin" />}
          Reported in error
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={busy != null}>
          Keep
        </Button>
      </div>
      {error && <p className="text-[12.5px] text-status-critical">{error}</p>}
    </div>
  );
}
