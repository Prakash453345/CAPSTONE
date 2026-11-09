import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CheckCircle2, FileVideo, Loader2, Upload, Video, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AnomalyTarget } from "@/components/map/CreateAnomalyPanel";
import { CommandError } from "@/services/traffic/commands";
import { clipFileProblem, uploadClip } from "@/services/traffic/clips";
import { useClipStore } from "@/store/clipStore";
import { useSystemStore } from "@/store/systemStore";
import { cn } from "@/utils/cn";
import { roadLabel } from "@/data/network";

const ACCEPT = ".mp4,.mov,.avi,.mkv,.webm,.m4v,video/*";
const REVIEW_PATH = "/console/anomalies";

/**
 * Upload a road video for automatic incident detection. The video stands in
 * for a camera on the chosen road: the vision service looks for accidents,
 * fire or smoke, stalled vehicles and congestion, and anything it finds waits
 * in Incidents › To review for a person to confirm.
 */
export function UploadClipPanel({ target, onClose }: { target: AnomalyTarget; onClose: () => void }) {
  const live = useSystemStore((s) => s.dataMode === "live");
  const upsert = useClipStore((s) => s.upsert);
  const selectClip = useClipStore((s) => s.selectClip);
  const navigate = useNavigate();
  const onReviewPage = useLocation().pathname.startsWith(REVIEW_PATH);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doneId, setDoneId] = useState<string | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const road = roadLabel(target.edgeId);

  useEffect(() => () => cancelRef.current?.(), []);

  const choose = (f: File | null | undefined) => {
    const problem = f ? clipFileProblem(f) : null;
    setError(problem);
    setFile(f && !problem ? f : null);
  };

  const start = async () => {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      const { done, cancel } = uploadClip(
        file,
        { edgeId: target.edgeId, roadName: road, at: target.at },
        setProgress,
      );
      cancelRef.current = cancel;
      const clip = await done;
      upsert(clip);
      setDoneId(clip.id);
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Backend unreachable. Is the api-service running?"
            : err.detail
          : "Upload failed.",
      );
    } finally {
      cancelRef.current = null;
      setProgress(null);
    }
  };

  return (
    <div className="pointer-events-auto w-[320px] max-w-full origin-top-left animate-sheet-in overflow-hidden rounded-xl bg-surface-raised shadow-elevation-3">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Video className="size-4 text-primary" />
          <span className="text-sm font-semibold">Check a road video</span>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="grid size-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-3.5"
        >
          <X />
        </button>
      </div>

      <div className="space-y-3 p-3">
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          The video is treated as a camera on <span className="font-medium text-foreground">{road}</span>. It is
          checked for accidents, fire or smoke, stalled vehicles and congestion. Anything found waits for a
          person to confirm before units are sent.
        </p>

        {!live && (
          <p className="rounded-md bg-status-warn-muted px-2.5 py-1.5 text-[12px] text-status-warn">
            Video checks run on the live backend. Switch to Live to upload.
          </p>
        )}

        {doneId ? (
          <div className="space-y-3">
            <p className="flex items-start gap-2 rounded-md bg-status-ok-muted px-2.5 py-2 text-[12.5px] text-status-ok">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
              Uploaded. Analysis has started; you'll get a notification when it's done.
            </p>
            <div className="flex gap-2">
              {!onReviewPage && (
                <Button
                  variant="primary"
                  className="flex-1"
                  onClick={() => {
                    selectClip(doneId);
                    navigate(REVIEW_PATH);
                  }}
                >
                  Follow it in Incidents
                </Button>
              )}
              <Button variant="outline" className="flex-1" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                choose(e.dataTransfer.files[0]);
              }}
              className={cn(
                "flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed px-3 py-5 text-center transition-colors",
                dragging ? "border-primary bg-primary-muted" : "border-border hover:bg-muted",
                (!live || progress !== null) && "pointer-events-none opacity-60",
              )}
            >
              {file ? <FileVideo className="size-5 text-primary" /> : <Upload className="size-5 text-muted-foreground" />}
              <span className="max-w-full truncate text-[13px] font-medium text-foreground">
                {file ? file.name : "Choose a video or drop it here"}
              </span>
              <span className="text-[11.5px] text-muted-foreground">
                {file ? `${(file.size / 1e6).toFixed(1)} MB` : "MP4, MOV, AVI, MKV or WebM"}
              </span>
              <input
                type="file"
                accept={ACCEPT}
                className="sr-only"
                disabled={!live || progress !== null}
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </label>

            {progress !== null && (
              <div aria-live="polite">
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width]"
                    style={{ width: `${Math.round(progress * 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-[11.5px] text-muted-foreground">Uploading… {Math.round(progress * 100)}%</p>
              </div>
            )}

            {error && (
              <p role="alert" className="rounded-md bg-status-critical-muted px-2.5 py-1.5 text-[12px] text-status-critical">
                {error}
              </p>
            )}

            <div className="flex gap-2">
              {progress !== null ? (
                <Button variant="outline" className="w-full" onClick={() => cancelRef.current?.()}>
                  <Loader2 className="size-4 animate-spin" />
                  Cancel upload
                </Button>
              ) : (
                <Button variant="primary" className="w-full" onClick={start} disabled={!file || !live}>
                  <Upload className="size-4" />
                  Upload and check
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
