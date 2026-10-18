import { useRef } from "react";

/**
 * Returns a function that says whether a layer's data really changed. The data
 * feed delivers a fresh object every second even when nothing on the road has
 * moved, and handing identical data to MapLibre still re-tiles the source and
 * redraws the whole map. Layers compare a cheap signature and skip the rest.
 */
export function useChangeGuard() {
  const last = useRef<string | null>(null);
  return (signature: string): boolean => {
    if (signature === last.current) return false;
    last.current = signature;
    return true;
  };
}
