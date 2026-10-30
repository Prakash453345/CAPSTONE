import { motion, type MotionValue, useTransform } from "framer-motion";
import type { ReactNode } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Fade-up, once, as the element enters the viewport. */
export function Reveal({
  children,
  delay = 0,
  className,
  y = 20,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  y?: number;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -12% 0px" }}
      transition={{ duration: 0.8, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Masked line-by-line headline reveal. Each entry of `lines` is one line. */
export function Lines({
  lines,
  as = "h2",
  className,
  play,
}: {
  lines: ReactNode[];
  as?: "h1" | "h2" | "h3";
  className?: string;
  /** Controlled mode (hero): reveal when true instead of on scroll. */
  play?: boolean;
}) {
  // The heading itself is what's watched: each line starts clipped out of
  // view by its mask, so watching the lines would never see them arrive.
  const Tag = motion[as];
  return (
    <Tag
      className={className}
      initial="hide"
      {...(play === undefined
        ? { whileInView: "show", viewport: { once: true, margin: "0px 0px -8% 0px" } }
        : { animate: play ? "show" : "hide" })}
    >
      {lines.map((line, i) => (
        <span className="reveal-line" key={i}>
          <motion.span
            variants={{ hide: { y: "110%" }, show: { y: "0%" } }}
            transition={{ duration: 0.9, delay: 0.06 * i, ease: EASE }}
          >
            {line}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}

/** A word whose opacity is scrubbed by scroll (manifesto). */
export function ScrubWord({
  progress,
  range,
  children,
  className,
}: {
  progress: MotionValue<number>;
  range: [number, number];
  children: ReactNode;
  className?: string;
}) {
  const opacity = useTransform(progress, range, [0.18, 1]);
  return (
    <motion.span className={`w ${className ?? ""}`} style={{ opacity }}>
      {children}
    </motion.span>
  );
}

/** The "›" after a text link, as on most product pages. */
export const ChevronIcon = () => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
    <path d="M3.5 1.5L7 5l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
