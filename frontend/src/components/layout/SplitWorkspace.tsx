import { useCallback, useEffect, useRef, useState } from "react";
import { AnomaliesPage } from "@/app/anomalies/AnomaliesPage";
import { TrafficPage } from "@/app/traffic/TrafficPage";
import { clampSplitRatio } from "@/utils/splitRatio";

const RATIO_KEY = "traffix.split.ratio";

function readRatio(): number {
  try {
    return clampSplitRatio(localStorage.getItem(RATIO_KEY));
  } catch {
    return clampSplitRatio(null);
  }
}

/**
 * The Single/Split `systemStore.viewMode` control's real content (Phase 8):
 * Anomaly Detection and Traffic Management side by side. Each pane is the
 * exact same page a direct nav click would show — reused wholesale rather
 * than rebuilt — so both stay backed by the same `incidentStore`/
 * `trafficStore`/`mapStore` a single-pane view uses, no parallel data path.
 *
 * Because both panes mount their own `TrafficMap`, and every `TrafficMap`
 * reads the same shared `mapStore.center`/`zoom`/`focus`, focusing one pane's
 * map moves both — that's what makes "View traffic in this area" (on an
 * anomaly, `AnomaliesPage`) work with no bespoke cross-pane plumbing: it's
 * the same `focusOn` every workspace already calls.
 */
export function SplitWorkspace() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [ratio, setRatio] = useState(readRatio);
  const draggingRef = useRef(false);

  useEffect(() => {
    try {
      localStorage.setItem(RATIO_KEY, String(ratio));
    } catch {
      /* storage unavailable -- non-fatal */
    }
  }, [ratio]);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    draggingRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const next = (e.clientX - rect.left) / rect.width;
    setRatio(clampSplitRatio(next));
  }, []);

  const stopDragging = useCallback(() => {
    draggingRef.current = false;
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex h-full w-full"
      onPointerMove={onPointerMove}
      onPointerUp={stopDragging}
      onPointerLeave={stopDragging}
    >
      <div
        className="flex min-w-0 flex-col overflow-hidden"
        style={{ width: `${ratio * 100}%` }}
      >
        <PaneHeader label="Anomaly Detection" />
        <div className="min-h-0 flex-1">
          <AnomaliesPage />
        </div>
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panes"
        onPointerDown={onPointerDown}
        onDoubleClick={() => setRatio(0.5)}
        title="Drag to resize · double-click to reset"
        className="group relative w-1.5 shrink-0 cursor-col-resize touch-none bg-border/60 hover:bg-primary/40"
      >
        <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border group-hover:bg-primary/60" />
      </div>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PaneHeader label="Traffic Management" />
        <div className="min-h-0 flex-1">
          <TrafficPage />
        </div>
      </div>
    </div>
  );
}

function PaneHeader({ label }: { label: string }) {
  return (
    <div className="shrink-0 border-b border-border bg-surface px-3 py-1.5 text-[12px] font-medium text-muted-foreground">
      {label}
    </div>
  );
}
