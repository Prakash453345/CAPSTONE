import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, X } from "lucide-react";
import { useNotificationStore } from "@/store/notificationStore";
import { TONE_META } from "@/components/notifications/meta";
import { Button } from "@/components/ui/button";
import { formatRelative } from "@/utils/format";
import { cn } from "@/utils/cn";

/** Top-bar bell: unread badge + a short history dropdown, backed by the same
 *  `notificationStore` the toaster reads. Opening it marks everything read —
 *  the dropdown itself is the "seen" affordance, no separate read/unread list. */
export function NotificationBell() {
  const items = useNotificationStore((s) => s.items);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const dismiss = useNotificationStore((s) => s.dismiss);
  const clear = useNotificationStore((s) => s.clear);

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    markAllRead();
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <Button
        variant="subtle"
        size="icon-sm"
        aria-label="Notifications"
        aria-expanded={open}
        className="relative"
        onClick={() => setOpen((o) => !o)}
      >
        <Bell />
        {unreadCount > 0 && (
          <span className="absolute right-1 top-1 grid size-3.5 place-items-center rounded-full bg-status-critical text-[9px] font-semibold leading-none text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </Button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full z-50 mt-2 w-80 max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-lg border border-border bg-surface-raised shadow-panel"
          >
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <span className="text-xs font-semibold text-foreground">Notifications</span>
              {items.length > 0 && (
                <button
                  type="button"
                  onClick={clear}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  Clear all
                </button>
              )}
            </div>

            <div className="max-h-80 overflow-y-auto">
              {items.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                  No notifications yet
                </p>
              ) : (
                items.map((ev) => {
                  const meta = TONE_META[ev.tone];
                  const Icon = meta.icon;
                  return (
                    <div
                      key={ev.id}
                      className="group flex items-start gap-2 border-b border-border/60 px-3 py-2 last:border-b-0 hover:bg-surface"
                    >
                      <Icon className={cn("mt-0.5 size-3.5 shrink-0", meta.text)} />
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-medium text-foreground">{ev.title}</p>
                        <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                          {ev.message}
                        </p>
                        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">
                          {formatRelative(new Date(ev.atMs))}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => dismiss(ev.id)}
                        aria-label="Dismiss"
                        className="shrink-0 rounded p-0.5 text-muted-foreground/50 opacity-0 hover:text-foreground group-hover:opacity-100"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
