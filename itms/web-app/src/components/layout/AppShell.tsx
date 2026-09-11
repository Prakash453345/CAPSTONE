import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { SideNav } from "@/components/layout/SideNav";
import { TopBar } from "@/components/layout/TopBar";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/notifications/Toaster";
import { TrafficDataBridge } from "@/services/traffic/TrafficDataBridge";
import { useSystemStore } from "@/store/systemStore";

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
        <main className="min-h-0 flex-1 overflow-auto">
          {viewMode === "split" ? <SplitWorkspace /> : <Outlet />}
        </main>
      </div>
    </div>
  );
}
