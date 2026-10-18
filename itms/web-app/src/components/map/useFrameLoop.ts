import { useEffect, useRef } from "react";

/**
 * Runs `step` on animation frames, but only while `active`, and no faster than
 * `maxFps`. Pulsing map rings used to run an unconditional 60 fps loop that
 * rewrote paint properties every frame, which keeps MapLibre redrawing the
 * whole map (roads, buildings, every signal) even when nothing on screen is
 * moving. With nothing to pulse there is no loop, and an idle map is idle.
 */
export function useFrameLoop(active: boolean, step: (nowMs: number) => void, maxFps = 30) {
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    if (!active) return;
    const gap = 1000 / maxFps;
    let raf = 0;
    let last = 0;
    const tick = (t: number) => {
      if (t - last >= gap) {
        last = t;
        stepRef.current(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, maxFps]);
}
