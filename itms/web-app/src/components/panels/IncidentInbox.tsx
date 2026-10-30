import { useEffect, useState } from "react";
import { ScanEye, MapPin, Loader2, RefreshCw } from "lucide-react";
import { useIncidentStore } from "@/store/incidentStore";
import { useAuthStore } from "@/store/authStore";
import { useSystemStore } from "@/store/systemStore";
import { useMapStore } from "@/store/mapStore";
import { fetchIncidents, reviewIncident } from "@/services/traffic/incidents";
import { shortJunctionName } from "@/data/network";
import type { Incident } from "@/types";

export function IncidentInbox() {
  const incidents = useIncidentStore((s) => s.incidents);
  const mode = useSystemStore((s) => s.dataMode);
  const [registry, setRegistry] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const focusOn = useMapStore((s) => s.focusOn);
  useEffect(() => {
    if (mode !== "live") {
      setRegistry([]);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    fetchIncidents(controller.signal)
      .then((rows) => {
        setRegistry(rows);
        setError(null);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "Incident registry unavailable. Streamed reports remain visible.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [mode, revision]);
  // Prefer current stream state over the initial registry snapshot.
  const rows = Array.from(
    new Map([...registry, ...incidents].map((i) => [i.id, i])).values(),
  ).sort(
    (a, b) =>
      Number(b.status === "candidate") - Number(a.status === "candidate") ||
      Date.parse(b.detectedAt) - Date.parse(a.detectedAt),
  );
  return (
    <section aria-labelledby="incident-review-h">
      <div className="flex items-start justify-between gap-3 px-2 pb-2">
        <div>
          <h2 id="incident-review-h" className="text-[13px] font-medium text-muted-foreground">
            Incident review
          </h2>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
            Candidates from the detection model wait here for a person to confirm or reject them.
          </p>
        </div>
        <button
          aria-label="Refresh incident registry"
          title="Refresh"
          disabled={mode !== "live" || loading}
          onClick={() => setRevision((n) => n + 1)}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
        </button>
      </div>
      {error && (
        <p role="alert" className="mx-2 mb-2 rounded-xl bg-status-warn-muted px-3 py-2 text-[12.5px] text-status-warn">
          {error}
        </p>
      )}
      {!rows.length && (
        <div className="flex flex-col items-center px-6 py-8 text-center">
          <span className="grid size-11 place-items-center rounded-2xl bg-muted text-muted-foreground">
            <ScanEye size={20} />
          </span>
          <p className="mt-3 text-sm font-medium text-foreground">
            {loading ? "Loading incident registry" : "No incident reports received"}
          </p>
          <p className="mt-1 max-w-[30ch] text-[12.5px] text-muted-foreground">
            An empty queue is not proof of an incident-free network: detection needs a trained model.
          </p>
        </div>
      )}
      <ul className="space-y-2">
        {rows.map((i) => {
          const pending = i.status === "candidate";
          return (
            <li key={i.id} className="rounded-2xl bg-surface p-3.5 shadow-elevation-1">
              <button
                className="flex w-full items-start gap-3 text-left"
                onClick={() => {
                  useIncidentStore.getState().selectIncident(i.id);
                  focusOn(i, 17);
                }}
              >
                <span
                  className={
                    "grid size-9 shrink-0 place-items-center rounded-xl " +
                    (pending ? "bg-status-warn-muted text-status-warn" : "bg-status-ok-muted text-status-ok")
                  }
                >
                  <MapPin size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <strong className="truncate text-[13.5px] font-medium capitalize text-foreground">
                      {i.type === "unknown" ? "Unclassified incident" : i.type}
                    </strong>
                    <span className={"shrink-0 text-[12px] font-medium " + (pending ? "text-status-warn" : "text-status-ok")}>
                      {i.resolution ?? i.status}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[12.5px] text-muted-foreground">
                    {shortJunctionName(i.affectedIntersection ?? "unknown")}, {Math.round(i.confidence * 100)}% confidence
                  </span>
                  <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted">
                    <span className="block h-full rounded-full bg-status-warn" style={{ width: `${Math.round(i.confidence * 100)}%` }} />
                  </span>
                </span>
              </button>
              {pending &&
                (mode === "simulation" ? (
                  <p className="mt-3 text-[12px] text-muted-foreground">Demo report. Review is disabled.</p>
                ) : (
                  <ReviewForm
                    incident={i}
                    onReviewed={(next) => {
                      setRegistry((old) => old.map((r) => (r.id === next.id ? next : r)));
                      useIncidentStore.getState().applyReview(next);
                    }}
                  />
                ))}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ReviewForm({
  incident,
  onReviewed,
}: {
  incident: Incident;
  onReviewed: (i: Incident) => void;
}) {
  const [action, setAction] = useState<"confirm" | "reject" | null>(null);
  const actor = `operator:${useAuthStore((s) => s.user?.username ?? "console")}`;
  const [classification, setClassification] = useState("UNKNOWN");
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!action)
    return (
      <div className="mt-3 flex gap-2">
        <button className="review-choice" onClick={() => setAction("confirm")}>
          Review & confirm
        </button>
        <button className="review-choice" onClick={() => setAction("reject")}>
          Reject report
        </button>
      </div>
    );
  return (
    <form
      className="review-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const next = await reviewIncident(
            incident.id,
            action,
            "",
            actor,
            classification,
            detail,
          );
          if (!next)
            throw new Error(
              "Unexpected review response. Refresh the registry before retrying.",
            );
          onReviewed(next);
          setAction(null);
        } catch (err) {
          setError(
            err instanceof Error ? err.message : "Review failed. Please retry.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <p>
        {action === "confirm"
          ? "Confirm this incident?"
          : "Reject this candidate as a false alarm?"}
      </p>
      <small>Recorded as {actor} (your signed-in account).</small>
      {action === "confirm" && (
        <label>
          Classification
          <select
            value={classification}
            onChange={(e) => setClassification(e.target.value)}
          >
            {[
              "UNKNOWN",
              "STALL",
              "LANE_BLOCK",
              "DEBRIS",
              "WRONG_WAY",
              "QUEUE_SPILLBACK",
            ].map((v) => (
              <option key={v} value={v}>
                {v.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Review notes
        <textarea
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          rows={2}
        />
      </label>
      {error && (
        <p role="alert" className="text-status-critical">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          className="review-choice"
          type="submit"
          disabled={busy}
        >
          {busy ? "Submitting…" : `Submit ${action}`}
        </button>
        <button
          className="review-choice"
          type="button"
          disabled={busy}
          onClick={() => {
            setAction(null);
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
