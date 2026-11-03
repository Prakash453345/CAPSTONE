import { createContext, useContext, useEffect, useState } from "react";

/**
 * Map-first layout, as in Apple Maps: on wide screens the Overview's map runs
 * edge to edge under the whole window, and the sidebar, the status bar and
 * the briefing float over it as glass. Below `lg` the console keeps its
 * docked layout, where there is no room for anything to float.
 */
export const MAP_FIRST_PATHS = new Set(["/console"]);

/** Sidebar widths, shared with the map so it can frame what is not covered. */
export const NAV_WIDTH = { expanded: 256, collapsed: 72 } as const;

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

export const useWide = () => useMediaQuery("(min-width: 1024px)");

/** How far shell chrome covers the map's left edge, in px. */
export const ShellInsetContext = createContext(0);
export const useShellInset = () => useContext(ShellInsetContext);
