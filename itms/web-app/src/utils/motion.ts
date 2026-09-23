/**
 * True when the operator has asked the OS to cut motion.
 * MapLibre paints outside CSS and Framer Motion, so its layers must consult this directly.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
