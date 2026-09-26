import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { SourceBanner } from "@/components/layout/SourceBanner";
import { Outlet } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { SideNav } from "@/components/layout/SideNav";
import { TopBar } from "@/components/layout/TopBar";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/notifications/Toaster";
import { TrafficDataBridge } from "@/services/traffic/TrafficDataBridge";
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
  const viewMode = useSystemStore((s) => s.viewMode);
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
    <div className="flex h-full w-full overflow-hidden bg-background text-foreground">
      <a href="#workspace" className="skip-link">Skip to workspace</a>
      <TrafficDataBridge />
      <Toaster />
      <div className="hidden lg:block">
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
                <SideNav
                  collapsed={false}
                  onToggleCollapsed={() => setDrawerOpen(false)}
                  onNavigate={() => setDrawerOpen(false)}
                />
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
        <TopBar onOpenNav={() => setDrawerOpen(true)} />
        <SourceBanner />
        <main id="workspace" tabIndex={-1} className="min-h-0 flex-1 overflow-auto">
          {viewMode === "split" ? (
            <Suspense fallback={null}>
              <SplitWorkspace />
            </Suspense>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
