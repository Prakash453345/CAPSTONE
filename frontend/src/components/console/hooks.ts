import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

/** Closes on outside click and Escape; returns focus to the trigger. */
export function useDismiss(open: boolean, onClose: () => void, refs: RefObject<HTMLElement | null>[]) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (refs.some((r) => r.current?.contains(e.target as Node))) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
    // refs are stable objects
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onClose]);
}

/** "12s ago" that keeps itself current. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function ago(ms: number, now = Date.now()) {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

/**
 * Style for a pill that slides under whichever child matches `selector`,
 * measured from the DOM and moved with a plain CSS transition. (Framer's
 * shared-layout animation was avoided on purpose: inside an exiting popover it
 * could stall every AnimatePresence exit in the app.) The first placement
 * doesn't animate; later moves glide.
 */
export function useIndicator(container: RefObject<HTMLElement | null>, selector: string, deps: unknown[]): CSSProperties {
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const placed = useRef(false);
  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const measure = () => {
      const el = root.querySelector<HTMLElement>(selector);
      if (!el) return setBox(null);
      const c = root.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      setBox({ x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    if (box) {
      const id = requestAnimationFrame(() => (placed.current = true));
      return () => cancelAnimationFrame(id);
    }
  }, [box]);
  if (!box) return { opacity: 0 };
  return {
    transform: `translate(${box.x}px, ${box.y}px)`,
    width: box.w,
    height: box.h,
    opacity: 1,
    transition: placed.current
      ? "transform 320ms cubic-bezier(.22,1,.36,1), width 320ms cubic-bezier(.22,1,.36,1), height 320ms cubic-bezier(.22,1,.36,1)"
      : "none",
  };
}
