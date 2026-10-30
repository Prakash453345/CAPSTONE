/**
 * Pure helpers for `SplitWorkspace`'s resizable divider, kept dependency-free
 * (no React/MapLibre imports) so they're testable without dragging in the
 * whole component tree — `SplitWorkspace.tsx` itself transitively imports
 * `TrafficMap`, which is not safe to load under the `node` test environment.
 */

export const MIN_SPLIT_RATIO = 0.25;
export const MAX_SPLIT_RATIO = 0.75;
const DEFAULT_SPLIT_RATIO = 0.5;

/** Clamp a candidate left-pane fraction into the allowed range, falling back
 *  to the 50/50 default for `null`/`undefined`/empty-string/anything that
 *  isn't a finite number (e.g. `localStorage.getItem` returning `null` when
 *  nothing's been saved yet -- `Number(null)` is `0`, a false-finite trap). */
export function clampSplitRatio(n: unknown): number {
  if (n == null || n === "") return DEFAULT_SPLIT_RATIO;
  const num = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(num)) return DEFAULT_SPLIT_RATIO;
  return Math.min(MAX_SPLIT_RATIO, Math.max(MIN_SPLIT_RATIO, num));
}
