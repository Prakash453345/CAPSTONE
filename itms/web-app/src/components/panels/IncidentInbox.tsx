import { useEffect, useState } from "react";
import { ScanEye, MapPin, Loader2, RefreshCw } from "lucide-react";
import { useIncidentStore } from "@/store/incidentStore";
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
    <section className="incident-inbox">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">HUMAN-IN-THE-LOOP</span>
          <h2>Incident review</h2>
        </div>
        <button
          aria-label="Refresh incident registry"
          disabled={mode !== "live" || loading}
          onClick={() => setRevision((n) => n + 1)}
        >
          {loading ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
        </button>
      </div>
      <p className="panel-footnote">
        Detection requires a trained M6 model. An empty inbox is not proof of an
        incident-free network.
      </p>
      {error && (
        <p role="alert" className="px-4 pb-3 text-xs text-status-warn">
          {error}
        </p>
      )}
      {!rows.length && (
        <div className="empty-copy">
          <ScanEye size={24} />
          <span>
            {loading
              ? "Loading incident registry…"
              : "No incident reports received."}
          </span>
        </div>
      )}
      {rows.map((i) => (
        <div key={i.id} className="incident-review-card">
          <button
            className="flex w-full items-start gap-2 text-left"
            onClick={() => {
              useIncidentStore.getState().selectIncident(i.id);
              focusOn(i, 17);
            }}
          >
            <MapPin size={14} className="mt-1 shrink-0 text-primary" />
            <span className="min-w-0 flex-1">
              <strong className="block text-xs font-medium capitalize">
                {i.type === "unknown" ? "Unclassified incident" : i.type}
              </strong>
              <small className="mt-1 block text-[10px] text-muted-foreground">
                {shortJunctionName(i.affectedIntersection ?? "unknown")} ·{" "}
                {Math.round(i.confidence * 100)}% model score
              </small>
            </span>
            <span className="text-[9px] uppercase text-status-warn">
              {i.resolution ?? i.status}
            </span>
          </button>
          {i.status === "candidate" &&
            (mode === "simulation" ? (
              <p className="mt-3 text-[10px] text-muted-foreground">
                Demo report · review disabled
              </p>
            ) : (
              <ReviewForm
                incident={i}
                onReviewed={(next) => {
                  setRegistry((old) =>
                    old.map((r) => (r.id === next.id ? next : r)),
                  );
                  useIncidentStore
                    .getState()
                    .setIncidents([
                      ...useIncidentStore
                        .getState()
                        .incidents.filter((r) => r.id !== next.id),
                      next,
                    ]);
                }}
              />
            ))}
        </div>
      ))}
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
  const [key, setKey] = useState("");
  const [actor, setActor] = useState("");
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
            key,
            actor.trim(),
            classification,
            detail,
          );
          if (!next)
            throw new Error(
              "Unexpected review response. Refresh the registry before retrying.",
            );
          onReviewed(next);
          setKey("");
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
      <label>
        Operator identity
        <input
          required
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="operator:your-name"
        />
      </label>
      <label>
        API key
        <input
          required
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </label>
      <small>Used for this request only. Not saved.</small>
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
          disabled={busy || !actor.trim()}
        >
          {busy ? "Submitting…" : `Submit ${action}`}
        </button>
        <button
          className="review-choice"
          type="button"
          disabled={busy}
          onClick={() => {
            setAction(null);
            setKey("");
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
