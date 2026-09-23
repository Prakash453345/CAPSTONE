import { create } from "zustand";

/**
 * Drives the landing→console "Globe-to-Console" cinematic (see
 * components/transition/GlobeTransition.tsx). A single flag is enough: the
 * transition owns its own phase sequencing internally once `active` flips
 * true, and flips it back via `finish()` when the reveal completes so the
 * sequence can replay on a later visit to the landing page.
 */
interface TransitionState {
  active: boolean;
  /** Starts the sequence; ignored if one is already running (duplicate-click guard). */
  start: () => void;
  finish: () => void;
}

export const useTransitionStore = create<TransitionState>((set, get) => ({
  active: false,
  start: () => {
    if (get().active) return;
    set({ active: true });
  },
  finish: () => set({ active: false }),
}));
