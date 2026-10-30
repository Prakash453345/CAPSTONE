import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, FileVideo, Loader2, MapPin, XCircle } from "lucide-react";
import { Button, Pill } from "@/components/console/kit";
import { ago, useNow } from "@/components/console/hooks";
import type { Tone } from "@/components/console/tone";
import { anomalyWord } from "@/components/console/words";
import { CommandError } from "@/services/traffic/commands";
import {
  CONFIRMABLE_TYPES,
  SEVERITIES,
  reviewClip,
  type Clip,
  type ClipSeverity,
} from "@/services/traffic/clips";
import { needsReview, useClipStore } from "@/store/clipStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";
import { edgeById } from "@/data/network";
import { cn } from "@/utils/cn";
import type { AnomalyKind } from "@/types";

const SEVERITY: Record<ClipSeverity, { word: string; tone: Tone }> = {
  low: { word: "Minor", tone: "warn" },
  medium: { word: "Moderate", tone: "warn" },
  high: { word: "Serious", tone: "critical" },
  blocked: { word: "Road blocked", tone: "critical" },
};

const DETECTOR_WORDS: Record<string, string> = {
  vehicles: "vehicle tracking",
  fire: "fire and smoke",
  accident: "accident model",
};

function focusEdge(edgeId: string) {
  const e = edgeById.get(edgeId);
  if (!e) return;
  const mid = e.path[Math.floor(e.path.length / 2)]!;
  useMapStore.getState().focusOn({ longitude: mid[0], latitude: mid[1] }, 16.5);
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Uploaded road videos: their analysis, and the review of what it found. */
export function ClipReview() {
  const clips = useClipStore((s) => s.clips);
  const selectedId = useClipStore((s) => s.selectedClipId);
  const selectClip = useClipStore((s) => s.selectClip);
  const live = useSystemStore((s) => s.dataMode === "live");
  const now = useNow(15_000);
  const toReview = clips.filter(needsReview).length;

  return (
    <section aria-labelledby="clip-review-h" className="mb-5">
      <div className="px-2 pb-2">
        <h2 id="clip-review-h" className="text-[13px] font-medium text-muted-foreground">
          Video checks{toReview ? ` · ${toReview} to review` : ""}
        </h2>
        <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
          Road videos checked for accidents, fire, stalled vehicles and congestion. Upload one from a road's card
          on the map.
        </p>
      </div>
      {!clips.length ? (
        <p className="mx-2 rounded-xl bg-muted/60 px-3 py-2.5 text-[12.5px] text-muted-foreground">
          {live ? "No videos uploaded yet." : "Video checks run on the live backend."}
        </p>
      ) : (
        <ul className="space-y-2">
          {clips.map((c) => (
            <li key={c.id} className={cn("rounded-2xl bg-surface p-3.5 shadow-elevation-1", c.id === selectedId && "ring-2 ring-primary/40")}>
              <button
                type="button"
                className="flex w-full items-start gap-3 text-left"
                aria-expanded={c.id === selectedId}
                onClick={() => {
                  selectClip(c.id === selectedId ? null : c.id);
                  if (c.edgeId) focusEdge(c.edgeId);
                }}
              >
                <ClipIcon clip={c} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13.5px] font-medium text-foreground">{headline(c)}</span>
                    <ClipPill clip={c} />
                  </span>
                  <span className="mt-0.5 block truncate text-[12.5px] text-muted-foreground">
                    {c.filename} · {c.roadName || c.edgeId} · {ago(c.submittedMs, now)}
                  </span>
                  {c.status === "ANALYSING" && (
                    <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted">
                      <span className="block h-full rounded-full bg-primary transition-[width]" style={{ width: `${Math.round(c.progress * 100)}%` }} />
                    </span>
                  )}
                </span>
              </button>
              {c.id === selectedId && <ClipDetail clip={c} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function headline(c: Clip): string {
  if (c.status === "QUEUED") return "Waiting to be checked";
  if (c.status === "ANALYSING") return `Checking… ${Math.round(c.progress * 100)}%`;
  if (c.status === "FAILED") return "Could not check this video";
  if (!c.anomalyType) return "Nothing unusual found";
  const type = c.review === "CONFIRMED" && c.confirmedType ? c.confirmedType : c.anomalyType;
  return anomalyWord(type);
}

function ClipIcon({ clip: c }: { clip: Clip }) {
  const base = "grid size-9 shrink-0 place-items-center rounded-xl";
  if (c.status === "QUEUED") return <span className={cn(base, "bg-muted text-muted-foreground")}><Clock size={16} /></span>;
  if (c.status === "ANALYSING") return <span className={cn(base, "bg-primary-muted text-primary")}><Loader2 size={16} className="animate-spin" /></span>;
  if (c.status === "FAILED") return <span className={cn(base, "bg-status-critical-muted text-status-critical")}><XCircle size={16} /></span>;
  if (!c.anomalyType) return <span className={cn(base, "bg-status-ok-muted text-status-ok")}><CheckCircle2 size={16} /></span>;
  return <span className={cn(base, "bg-status-warn-muted text-status-warn")}><AlertTriangle size={16} /></span>;
}

function ClipPill({ clip: c }: { clip: Clip }) {
  if (c.review === "CONFIRMED") return <Pill tone="ok">Confirmed</Pill>;
  if (c.review === "REJECTED") return <Pill tone="neutral">Rejected</Pill>;
  if (c.status === "DONE" && c.severity) {
    const s = SEVERITY[c.severity];
    return <Pill tone={s.tone}>{s.word}</Pill>;
  }
  return null;
}

function ClipDetail({ clip: c }: { clip: Clip }) {
  const video = useRef<HTMLVideoElement | null>(null);
  const seek = (s: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, s);
    void v.play().catch(() => undefined);
  };

  if (c.status === "QUEUED" || c.status === "ANALYSING")
    return (
      <p className="mt-3 text-[12.5px] text-muted-foreground">
        {c.status === "QUEUED"
          ? "Queued for the vision service. If this does not move, check that the clip worker is running (python -m vision_service.clips)."
          : "The vision service is going through the video. Results appear here when it finishes."}
      </p>
    );
  if (c.status === "FAILED")
    return <p className="mt-3 rounded-xl bg-status-critical-muted px-3 py-2 text-[12.5px] text-status-critical">{c.error || "Analysis failed."}</p>;

  const flagged = c.flaggedAtS;
  return (
    <div className="mt-3 space-y-3">
      <video
        ref={video}
        src={c.videoUrl}
        poster={c.snapshotUrl ?? undefined}
        controls
        preload="metadata"
        className="aspect-video w-full rounded-xl bg-black"
        onLoadedMetadata={(e) => {
          if (flagged != null) e.currentTarget.currentTime = Math.max(0, flagged - 2);
        }}
      />
      <div className="flex flex-wrap items-center gap-1.5">
        {flagged != null && (
          <Button variant="ghost" size="sm" icon={FileVideo} onClick={() => seek(flagged - 2)}>
            Jump to {clock(flagged)}
          </Button>
        )}
        {c.edgeId && (
          <Button variant="ghost" size="sm" icon={MapPin} onClick={() => focusEdge(c.edgeId)}>
            Show road
          </Button>
        )}
      </div>

      <Timeline clip={c} onSeek={seek} />

      {c.anomalyType ? (
        <div className="space-y-1.5">
          <p className="text-[12.5px] font-medium text-foreground">
            Why: {Math.round((c.confidence ?? 0) * 100)}% sure, rated {SEVERITY[c.severity ?? "medium"].word.toLowerCase()}
          </p>
          <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] leading-relaxed text-muted-foreground">
            {c.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {c.findings.length > 1 && (
            <p className="text-[12px] text-muted-foreground">
              Also seen:{" "}
              {c.findings
                .slice(1)
                .map((f) => `${anomalyWord(f.anomalyType).toLowerCase()} at ${clock(f.startS)}`)
                .join(", ")}
            </p>
          )}
        </div>
      ) : (
        <p className="text-[12.5px] text-muted-foreground">No accident, fire, stalled vehicle or congestion was found.</p>
      )}
      <p className="text-[11.5px] text-muted-foreground">
        Checked with: {c.detectors.map((d) => DETECTOR_WORDS[d] ?? d).join(", ") || "nothing"}.
        {!c.detectors.includes("accident") && " The accident model is not installed, so accidents can't be detected yet."}
      </p>

      {c.review === "PENDING" && <ClipReviewForm clip={c} />}
      {c.review === "CONFIRMED" && (
        <p className="rounded-xl bg-status-ok-muted px-3 py-2 text-[12.5px] text-status-ok">
          Confirmed by {c.reviewedBy} as {anomalyWord(c.confirmedType ?? "unknown").toLowerCase()} (
          {SEVERITY[c.confirmedSeverity ?? "medium"].word.toLowerCase()}). It is now on the road under "On the road"
          {c.confirmedSeverity === "low" ? "; minor disruptions don't send units." : ", and units are sent if any are available."}
        </p>
      )}
      {c.review === "REJECTED" && (
        <p className="rounded-xl bg-muted px-3 py-2 text-[12.5px] text-muted-foreground">
          Rejected by {c.reviewedBy}
          {c.reviewNote ? `: ${c.reviewNote}` : "."}
        </p>
      )}
    </div>
  );
}

/** Detector signals over the video, one line each, with the flagged moment
 *  marked. Click to seek. */
function Timeline({ clip: c, onSeek }: { clip: Clip; onSeek: (s: number) => void }) {
  const t = c.timeline.t ?? [];
  if (t.length < 2) return null;
  const series: { key: string; label: string; color: string; scale: number }[] = [];
  if (c.timeline.accident) series.push({ key: "accident", label: "Accident", color: "#e5484d", scale: 1 });
  if (c.timeline.fire) series.push({ key: "fire", label: "Fire / smoke", color: "#f5a524", scale: 1 });
  if (c.timeline.moving && c.timeline.vehicles) {
    const peak = Math.max(1, ...c.timeline.vehicles.map((v) => v ?? 0));
    series.push({ key: "vehicles", label: "Vehicles", color: "#6f8fff", scale: peak });
    series.push({ key: "moving", label: "Moving", color: "#46c46a", scale: peak });
  }
  if (!series.length) return null;
  const W = 300;
  const H = 54;
  const x = (i: number) => (i / (t.length - 1)) * W;
  const path = (vals: (number | null)[], scale: number) =>
    vals
      .map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${(H - 4 - (v / scale) * (H - 8)).toFixed(1)}`))
      .filter(Boolean)
      .map((p, i) => `${i ? "L" : "M"}${p}`)
      .join(" ");
  const flagged = c.flaggedAtS;
  return (
    <figure>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-14 w-full cursor-pointer rounded-lg bg-muted/50"
        preserveAspectRatio="none"
        role="img"
        aria-label="What the detectors saw over the video. Click to jump there."
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - box.left) / box.width) * (t.length - 1));
        }}
      >
        {flagged != null && (
          <line x1={x(flagged)} x2={x(flagged)} y1={0} y2={H} stroke="currentColor" className="text-foreground/40" strokeDasharray="3 3" />
        )}
        {series.map((s) => (
          <path key={s.key} d={path(c.timeline[s.key]!, s.scale)} fill="none" stroke={s.color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
        <span className="ml-auto">{clock(t.length - 1)}</span>
      </figcaption>
    </figure>
  );
}

function ClipReviewForm({ clip: c }: { clip: Clip }) {
  const upsert = useClipStore((s) => s.upsert);
  const [action, setAction] = useState<"confirm" | "reject" | null>(null);
  const [type, setType] = useState<AnomalyKind>(c.anomalyType ?? "accident");
  const [severity, setSeverity] = useState<ClipSeverity>(c.severity ?? "medium");
  const [actor, setActor] = useState("");
  const [key, setKey] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setType(c.anomalyType ?? "accident");
    setSeverity(c.severity ?? "medium");
  }, [c.anomalyType, c.severity]);

  if (!action)
    return (
      <div className="flex gap-2">
        <button className="review-choice" onClick={() => setAction("confirm")}>
          Review & confirm
        </button>
        <button className="review-choice" onClick={() => setAction("reject")}>
          Reject as false alarm
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
          upsert(await reviewClip(c.id, action, key, { actor: actor.trim(), note, anomalyType: type, severity }));
          setKey("");
          setAction(null);
        } catch (err) {
          setError(
            err instanceof CommandError
              ? err.status === 401
                ? "That API key was not accepted."
                : err.detail
              : "Review failed. Please retry.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <p>
        {action === "confirm"
          ? "Confirm and put it on the road? Units are sent for anything above minor."
          : "Reject this finding as a false alarm?"}
      </p>
      {action === "confirm" && (
        <>
          <label>
            What it is
            <select value={type} onChange={(e) => setType(e.target.value as AnomalyKind)}>
              {CONFIRMABLE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {anomalyWord(t)}
                </option>
              ))}
            </select>
          </label>
          <label>
            How bad
            <select value={severity} onChange={(e) => setSeverity(e.target.value as ClipSeverity)}>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY[s].word}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      <label>
        Operator identity
        <input required value={actor} onChange={(e) => setActor(e.target.value)} placeholder="e.g. operator:priya" />
      </label>
      <label>
        API key
        <input required type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
      </label>
      <small>Used for this request only. Not saved.</small>
      <label>
        Review notes
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
      </label>
      {error && (
        <p role="alert" className="text-status-critical">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button className="review-choice" type="submit" disabled={busy || !actor.trim() || !key}>
          {busy ? "Submitting…" : action === "confirm" ? "Confirm" : "Reject"}
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
