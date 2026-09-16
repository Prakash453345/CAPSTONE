/** MapLibre paints are outside CSS/Framer Motion; consult the same OS preference. */
export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
