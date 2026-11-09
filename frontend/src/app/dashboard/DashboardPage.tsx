import { motion } from "framer-motion";
import { TrafficMap } from "@/components/map/TrafficMap";
import { EASE_OUT } from "@/components/console/motion";
import { ActiveMissions, AttentionList, BusiestRoads, NetworkStatus, RecentEvents } from "@/components/console/briefing";
import { PanelPlainContext } from "@/components/console/panelContext";
import { useWide } from "@/components/layout/mapFirst";
import { FloatingBar } from "@/components/layout/TopBar";
import { useActiveRequests } from "@/store/emergencyStore";

/** The briefing sheet's width on wide screens, as Apple Maps' place card. */
const SHEET_W = 380;

/**
 * Overview: the live map, and beside it a short briefing read top to bottom:
 * how the network is doing, what needs a person, any emergency in progress,
 * then detail. On wide screens the map runs under the whole window and the
 * briefing floats over its right edge as one glass sheet (AppShell's
 * map-first layout); narrower, the two sit side by side or stacked.
 */
export function DashboardPage() {
  const active = useActiveRequests();
  const wide = useWide();
  const rail = [
    <NetworkStatus key="status" />,
    <AttentionList key="attention" />,
    active.length ? <ActiveMissions key="missions" requests={active} /> : null,
    <BusiestRoads key="roads" />,
    <RecentEvents key="recent" />,
  ].filter(Boolean);

  const cards = rail.map((card, i) => (
    <motion.div
      key={i}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: 0.06 * i, ease: EASE_OUT }}
    >
      {card}
    </motion.div>
  ));

  if (wide) {
    return (
      <div className="overview-page relative h-full">
        <h1 className="sr-only">Overview</h1>
        <TrafficMap insetRight={SHEET_W + 12} />
        <motion.aside
          aria-label="Briefing"
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, ease: EASE_OUT }}
          style={{ width: SHEET_W }}
          className="glass absolute bottom-3 right-3 top-3 z-20 flex flex-col rounded-[22px]"
        >
          {/* The top bar's status and account controls head the sheet. */}
          {/* Not clipped (no overflow-hidden on the sheet): its menus open past the header. */}
          <div className="relative z-10 shrink-0 border-b border-[var(--glass-edge)] px-2 py-1">
            <FloatingBar />
          </div>
          <PanelPlainContext.Provider value>
            <div className="min-h-0 flex-1 divide-y divide-[var(--glass-edge)] overflow-y-auto overscroll-contain rounded-b-[22px]">
              {cards}
            </div>
          </PanelPlainContext.Provider>
        </motion.aside>
      </div>
    );
  }

  return (
    <div className="overview-page grid h-full grid-cols-1 gap-4 px-4 pb-4 sm:px-6 sm:pb-6 lg:grid-cols-[minmax(0,1fr)_minmax(340px,380px)]">
      <motion.section
        aria-label="Live map"
        initial={{ opacity: 0, scale: 0.99 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, ease: EASE_OUT }}
        className="relative min-h-[460px] overflow-hidden rounded-2xl bg-surface shadow-elevation-1 lg:h-full"
      >
        <TrafficMap />
      </motion.section>
      <aside aria-label="Briefing" className="flex min-h-0 flex-col gap-4 lg:overflow-y-auto lg:pb-2 lg:pr-1">
        {cards}
      </aside>
    </div>
  );
}
