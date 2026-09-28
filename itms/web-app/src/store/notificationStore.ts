import { create } from "zustand";
import type { NotificationEvent } from "@/types";

/**
 * Global notification history: every `NotificationEvent` the data layer has
 * classified as worth surfacing (Phase 5), newest first. `Toaster` renders a
 * short-lived pop-up for each new arrival off this same list; the bell
 * dropdown in `TopBar` renders the list itself. Deliberately small and
 * store-only — no per-item "visible" flag here, so pushing an event can never
 * silently depend on whether a toast happened to be mounted.
 */

const MAX_ITEMS = 40;

interface NotificationState {
  items: NotificationEvent[];
  unreadCount: number;

  push: (events: NotificationEvent[]) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  items: [],
  unreadCount: 0,

  push: (events) =>
    set((s) => {
      if (events.length === 0) return s;
      return {
        items: [...events, ...s.items].slice(0, MAX_ITEMS),
        unreadCount: s.unreadCount + events.length,
      };
    }),
  markAllRead: () => set({ unreadCount: 0 }),
  dismiss: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
  clear: () => set({ items: [], unreadCount: 0 }),
}));
