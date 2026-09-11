import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useNotificationStore } from "@/store/notificationStore";
import { TONE_META } from "@/components/notifications/meta";
import { cn } from "@/utils/cn";
import type { NotificationEvent } from "@/types";

const AUTO_DISMISS_MS = 6_000;
const MAX_VISIBLE = 4;

/**
 * Pop-up toast stack, mounted once by `AppShell`. Purely reactive to
 * `notificationStore.items` — it never decides *whether* something is
 * notify-worthy (that's `services/traffic/notifications.ts`), only how long
 * a given arrival stays on screen before it self-dismisses.
 */
export function Toaster() {
  const items = useNotificationStore((s) => s.items);
  const [visible, setVisible] = useState<NotificationEvent[]>([]);
  const seen = useRef(new Set<string>());
  const timers = useRef(new Map<string, number>());

  useEffect(() => {
    const fresh = items.filter((i) => !seen.current.has(i.id));
    if (!fresh.length) return;
    for (const ev of fresh) seen.current.add(ev.id);
    // items is newest-first; fresh is too, so reverse before prepending to
    // keep the true arrival order in the visible stack.
    setVisible((v) => [...fresh].reverse().concat(v));
    for (const ev of fresh) {
      const t = window.setTimeout(() => dismiss(ev.id), AUTO_DISMISS_MS);
      timers.current.set(ev.id, t);
    }
  }, [items]);

  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const t of map.values()) window.clearTimeout(t);
    };
  }, []);

  function dismiss(id: string) {
    setVisible((v) => v.filter((e) => e.id !== id));
    const t = timers.current.get(id);
    if (t != null) {
      window.clearTimeout(t);
      timers.current.delete(id);
    }
  }

  return (
    <div className="pointer-events-none fixed right-3 top-16 z-[60] flex w-[21rem] max-w-[calc(100vw-1.5rem)] flex-col gap-2 sm:right-4">
      <AnimatePresence initial={false}>
        {visible.slice(0, MAX_VISIBLE).map((ev) => {
          const meta = TONE_META[ev.tone];
          const Icon = meta.icon;
          return (
            <motion.div
              key={ev.id}
              layout
              initial={{ opacity: 0, x: 32, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 32, scale: 0.94 }}
              transition={{ type: "spring", stiffness: 420, damping: 34 }}
              className={cn(
                "pointer-events-auto flex items-start gap-2.5 rounded-lg border p-3 shadow-lg backdrop-blur-sm",
                meta.border,
                meta.bg,
              )}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", meta.text)} />
              <div className="min-w-0 flex-1">
                <p className={cn("text-xs font-semibold", meta.text)}>{ev.title}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                  {ev.message}
                </p>
              </div>
              <button
                type="button"
                onClick={() => dismiss(ev.id)}
                aria-label="Dismiss notification"
                className="shrink-0 rounded p-0.5 text-muted-foreground/70 hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
