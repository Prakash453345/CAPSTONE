/** Shared motion curves for the console. */

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;
export const SPRING = { type: "spring", stiffness: 420, damping: 34, mass: 0.8 } as const;

/** Staggered entrance for a list of rows or cards. */
export const listMotion = {
  container: { hidden: {}, show: { transition: { staggerChildren: 0.04, delayChildren: 0.05 } } },
  item: {
    hidden: { opacity: 0, y: 8 },
    show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: EASE_OUT } },
  },
};
