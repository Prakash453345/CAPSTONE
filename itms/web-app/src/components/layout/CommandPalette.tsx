import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  Ambulance,
  Columns2,
  CornerDownLeft,
  FlaskConical,
  Moon,
  Radio,
  Route as RouteIcon,
  Search,
  Sun,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { NAV_ITEMS } from "@/app/nav";
import { roadEdges } from "@/data/network";
import { Kbd } from "@/components/console/kit";
import { EASE_OUT } from "@/components/console/motion";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore } from "@/store/themeStore";
import { useMapStore } from "@/store/mapStore";
import { PRESET_UNITS, useEmergencyStore } from "@/store/emergencyStore";
import { cn } from "@/utils/cn";

interface Command {
  id: string;
  group: "Go to" | "Roads" | "Actions";
  label: string;
  hint?: string;
  icon: LucideIcon;
  keywords?: string;
  run: () => void;
}

/**
 * The console's one search box: jump to a workspace, find a street, or start
 * an action, all from the keyboard.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const dataMode = useSystemStore((s) => s.dataMode);
  const theme = useThemeStore((s) => s.resolved);

  const commands = useMemo<Command[]>(() => {
    const go = NAV_ITEMS.map<Command>((n) => ({
      id: `go-${n.id}`,
      group: "Go to",
      label: n.label,
      hint: n.blurb,
      icon: n.icon,
      run: () => navigate(n.path),
    }));
    // one entry per street, focusing the map on its middle
    const streets = new Map<string, (typeof roadEdges)[number][]>();
    for (const e of roadEdges) {
      const name = e.name ?? "Service road";
      streets.set(name, [...(streets.get(name) ?? []), e]);
    }
    const roads = [...streets.entries()]
      .sort((a, b) => b[1].length - a[1].length)
      .map<Command>(([name, edges]) => {
        const mid = edges[Math.floor(edges.length / 2)]!;
        const p = mid.path[Math.floor(mid.path.length / 2)]!;
        const km = edges.reduce((t, e) => t + e.lengthM, 0) / 1000;
        return {
          id: `road-${name}`,
          group: "Roads",
          label: name,
          hint: `${edges.length} ${edges.length === 1 ? "segment" : "segments"}, ${km.toFixed(1)} km`,
          icon: RouteIcon,
          run: () => {
            navigate("/console/traffic");
            window.setTimeout(() => useMapStore.getState().focusOn({ longitude: p[0], latitude: p[1] }, 16), 60);
          },
        };
      });
    const actions: Command[] = [
      {
        id: "act-dispatch",
        group: "Actions",
        label: "Dispatch an emergency unit",
        hint: "Pick a start and a destination on the map",
        icon: Ambulance,
        keywords: "ambulance emergency route corridor",
        run: () => {
          navigate("/console/emergency");
          useEmergencyStore.getState().startDraft(PRESET_UNITS[0]!);
        },
      },
      {
        id: "act-anomaly",
        group: "Actions",
        label: "Report a disruption",
        hint: "Click the road where it is",
        icon: TriangleAlert,
        keywords: "anomaly incident accident breakdown block",
        run: () => {
          navigate("/console/anomalies");
          useMapStore.getState().setInteractionMode("create-anomaly");
        },
      },
      {
        id: "act-source",
        group: "Actions",
        label: dataMode === "simulation" ? "Switch to live data" : "Switch to demo data",
        icon: dataMode === "simulation" ? Radio : FlaskConical,
        keywords: "data source live demo simulation",
        run: () => useSystemStore.getState().setDataMode(dataMode === "simulation" ? "live" : "simulation"),
      },
      {
        id: "act-theme",
        group: "Actions",
        label: theme === "dark" ? "Use light appearance" : "Use dark appearance",
        icon: theme === "dark" ? Sun : Moon,
        keywords: "theme dark light appearance",
        run: () => useThemeStore.getState().setMode(theme === "dark" ? "light" : "dark"),
      },
      {
        id: "act-split",
        group: "Actions",
        label: "Open split view",
        hint: "Incidents and traffic side by side",
        icon: Columns2,
        keywords: "split compare layout",
        run: () => useSystemStore.getState().setViewMode("split"),
      },
    ];
    return [...go, ...actions, ...roads];
  }, [navigate, dataMode, theme]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    const words = q.split(/\s+/);
    return commands.filter((c) => {
      const hay = `${c.label} ${c.hint ?? ""} ${c.keywords ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      window.setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);
  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const runAt = (i: number) => {
    const c = results[i];
    if (!c) return;
    onClose();
    c.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => Math.min(results.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runAt(index);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  let lastGroup = "";
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[12vh]">
          <motion.div
            className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Search and commands"
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.22, ease: EASE_OUT }}
            className="relative w-full max-w-[600px] overflow-hidden rounded-2xl bg-surface-raised shadow-elevation-3"
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search className="size-[18px] shrink-0 text-muted-foreground" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKey}
                placeholder="Search roads, pages and actions"
                aria-label="Search roads, pages and actions"
                role="combobox"
                aria-expanded="true"
                aria-controls="palette-results"
                aria-activedescendant={results[index] ? `palette-${results[index]!.id}` : undefined}
                className="h-14 min-w-0 flex-1 bg-transparent text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
              <Kbd>Esc</Kbd>
            </div>
            <div ref={listRef} id="palette-results" role="listbox" className="max-h-[min(420px,60vh)] overflow-y-auto p-2">
              {results.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-muted-foreground">Nothing matches "{query}".</p>
              )}
              {results.map((c, i) => {
                const header = c.group !== lastGroup ? c.group : null;
                lastGroup = c.group;
                const active = i === index;
                return (
                  <div key={c.id}>
                    {header && <div className="px-3 pb-1 pt-3 text-[11.5px] font-medium text-muted-foreground">{header}</div>}
                    <button
                      type="button"
                      id={`palette-${c.id}`}
                      role="option"
                      aria-selected={active}
                      data-index={i}
                      onMouseMove={() => setIndex(i)}
                      onClick={() => runAt(i)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors duration-100",
                        active ? "bg-muted" : "hover:bg-muted/60",
                      )}
                    >
                      <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground", active && "bg-surface text-primary shadow-elevation-1")}>
                        <c.icon className="size-4" strokeWidth={1.9} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground">{c.label}</span>
                        {c.hint && <span className="block truncate text-[12.5px] text-muted-foreground">{c.hint}</span>}
                      </span>
                      {active && <CornerDownLeft className="size-4 shrink-0 text-muted-foreground" />}
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-4 border-t border-border px-4 py-2.5 text-[12px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> to move
              </span>
              <span className="flex items-center gap-1.5">
                <Kbd>Enter</Kbd> to open
              </span>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
