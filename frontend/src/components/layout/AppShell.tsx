import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useOutlet } from "react-router-dom";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { X } from "lucide-react";
import { SideNav } from "@/components/layout/SideNav";
import { TopBar } from "@/components/layout/TopBar";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { usePaletteShortcut } from "@/components/layout/usePaletteShortcut";
import { StatusMenu } from "@/components/layout/StatusMenu";
import { EASE_OUT } from "@/components/console/motion";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/notifications/Toaster";
import { TrafficDataBridge } from "@/services/traffic/TrafficDataBridge";
import { ClipBridge } from "@/services/traffic/ClipBridge";
import { useSystemStore } from "@/store/systemStore";

// Split view mounts two map pages, so it pulls in MapLibre; loading it on
// demand keeps the map library out of the landing page's first download.
const SplitWorkspace = lazy(() =>
  import("@/components/layout/SplitWorkspace").then((m) => ({ default: m.SplitWorkspace })),
);

const COLLAPSE_KEY = "traffix.nav.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * App frame: persistent left rail + top bar + routed workspace.
 * - lg and up: docked rail, collapse state persisted to localStorage.
 * - below lg: rail hidden, opened as an overlay drawer from the top bar.
 */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  usePaletteShortcut(openPalette);
  const { pathname } = useLocation();
  const viewMode = useSystemStore((s) => s.viewMode);
  // The full-screen map route: rail and top bar step aside; data, alerts and
  // the demo notice stay. Split view never applies there.
  const immersive = pathname === "/console/map";
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const drawer = drawerRef.current;
    const focusable = () => Array.from(drawer?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? []);
    focusable()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setDrawerOpen(false); }
      if (e.key !== "Tab") return;
      const items = focusable(), first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [drawerOpen]);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* storage unavailable — non-fatal */
    }
  }, [collapsed]);

  // Close the mobile drawer once the viewport is wide enough for the docked rail.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const onChange = () => mq.matches && setDrawerOpen(false);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return (
    <MotionConfig reducedMotion="user">
    <div className="flex h-full w-full overflow-hidden bg-background text-foreground">
      <a href="#workspace" className="skip-link">Skip to workspace</a>
      <TrafficDataBridge />
      <ClipBridge />
      <Toaster />
      <div className={immersive ? "hidden" : "hidden lg:block"}>
        <SideNav
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((c) => !c)}
        />
      </div>

      <AnimatePresence>
        {drawerOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/60 lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawerOpen(false)}
            />
            <motion.div
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              className="fixed inset-y-0 left-0 z-50 lg:hidden"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.2, ease: "easeOut" }}
            >
              <div className="relative h-full">
                <div className="h-full bg-background shadow-elevation-3">
                  <SideNav
                    collapsed={false}
                    onToggleCollapsed={() => setDrawerOpen(false)}
                    onNavigate={() => setDrawerOpen(false)}
                  />
                </div>
                <Button
                  variant="subtle"
                  size="icon-sm"
                  className="absolute right-2 top-2"
                  onClick={() => setDrawerOpen(false)}
                  aria-label="Close navigation"
                >
                  <X />
                </Button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        {!immersive && <TopBar onOpenNav={() => setDrawerOpen(true)} onOpenSearch={openPalette} />}
        <main id="workspace" tabIndex={-1} className="relative min-h-0 flex-1 overflow-hidden outline-none">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={viewMode === "split" && !immersive ? "split" : pathname}
              className="absolute inset-0 overflow-auto"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.12 } }}
              transition={{ duration: 0.3, ease: EASE_OUT }}
            >
              {viewMode === "split" && !immersive ? (
                <Suspense fallback={null}>
                  <SplitWorkspace />
                </Suspense>
              ) : (
                <FrozenOutlet />
              )}
            </motion.div>
          </AnimatePresence>
        </main>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        {immersive && (
          // the full-screen map hides the top bar, but never the data status
          <div className="absolute left-1/2 top-3 z-30 -translate-x-1/2 rounded-xl bg-surface-raised shadow-elevation-2">
            <StatusMenu />
          </div>
        )}
      </div>
    </div>
    </MotionConfig>
  );
}

/** The routed page as it was when this transition key mounted, so a page
 *  fading out keeps showing itself rather than the page replacing it. */
function FrozenOutlet() {
  const outlet = useOutlet();
  const [frozen] = useState(outlet);
  return frozen;
}
