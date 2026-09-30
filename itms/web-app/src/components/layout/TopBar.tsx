import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, Monitor, Moon, Search, Sun } from "lucide-react";
import { navItemFor } from "@/app/nav";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore, type ThemeMode } from "@/store/themeStore";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { StatusMenu } from "@/components/layout/StatusMenu";
import { IconButton, Kbd } from "@/components/console/kit";
import { EASE_OUT } from "@/components/console/motion";

/**
 * The top bar holds three things: where you are, a way to find anything, and
 * whether the data can be trusted. Everything else lives one click deeper.
 */
export function TopBar({ onOpenNav, onOpenSearch }: { onOpenNav: () => void; onOpenSearch: () => void }) {
  const { pathname } = useLocation();
  const viewMode = useSystemStore((s) => s.viewMode);
  const item = navItemFor(pathname);
  const title = viewMode === "split" ? "Split view" : item.label;
  const mac = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 px-4 sm:px-6">
      <IconButton label="Open navigation" icon={Menu} className="lg:hidden" onClick={onOpenNav} />

      <div className="relative min-w-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.h1
            key={title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2, ease: EASE_OUT }}
            className="truncate text-[17px] font-semibold tracking-[-0.015em] text-foreground"
          >
            {title}
          </motion.h1>
        </AnimatePresence>
      </div>

      <button
        type="button"
        onClick={onOpenSearch}
        className="hidden h-9 w-[min(34vw,340px)] items-center gap-2.5 rounded-xl bg-surface px-3 text-[13.5px] text-muted-foreground shadow-elevation-1 transition-shadow hover:shadow-elevation-2 md:flex"
      >
        <Search className="size-4" />
        <span className="flex-1 text-left">Search roads, pages, actions</span>
        <Kbd>{mac ? "⌘" : "Ctrl"}</Kbd>
        <Kbd>K</Kbd>
      </button>
      <IconButton label="Search" icon={Search} className="md:hidden" onClick={onOpenSearch} />

      <div className="flex items-center gap-1">
        <StatusMenu />
        <NotificationBell />
        <ThemeButton />
      </div>
    </header>
  );
}

const THEME_NEXT: Record<ThemeMode, ThemeMode> = { system: "light", light: "dark", dark: "system" };
const THEME_META: Record<ThemeMode, { icon: typeof Sun; label: string }> = {
  system: { icon: Monitor, label: "Appearance: match system" },
  light: { icon: Sun, label: "Appearance: light" },
  dark: { icon: Moon, label: "Appearance: dark" },
};

/** Cycles system, light, dark. */
function ThemeButton() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  const { icon, label } = THEME_META[mode];
  return <IconButton label={`${label}. Click to change.`} icon={icon} onClick={() => setMode(THEME_NEXT[mode])} />;
}
