import { motion } from "framer-motion";
import { TrafficMap } from "@/components/map/TrafficMap";
import { EASE_OUT } from "@/components/console/motion";
import { ActiveMissions, AttentionList, BusiestRoads, NetworkStatus, RecentEvents } from "@/components/console/briefing";
import { useActiveRequests } from "@/store/emergencyStore";

/**
 * Overview: the live map, and beside it a short briefing read top to bottom:
 * how the network is doing, what needs a person, any emergency in progress,
 * then detail.
 */
export function DashboardPage() {
  const active = useActiveRequests();
  const rail = [
    <NetworkStatus key="status" />,
    <AttentionList key="attention" />,
    active.length ? <ActiveMissions key="missions" requests={active} /> : null,
    <BusiestRoads key="roads" />,
    <RecentEvents key="recent" />,
  ].filter(Boolean);

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
        {rail.map((card, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.06 * i, ease: EASE_OUT }}
          >
            {card}
          </motion.div>
        ))}
      </aside>
    </div>
  );
}
