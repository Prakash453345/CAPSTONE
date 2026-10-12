import { motion, type MotionValue, useTransform } from "framer-motion";
import type { ReactNode } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Fade-up, once, as the element enters the viewport. */
export function Reveal({
  children,
  delay = 0,
  className,
  y = 28,
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
      transition={{ duration: 1.1, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Masked line-by-line headline reveal. Each entry of `lines` is one line. */
export function Lines({
  lines,
  as: Tag = "h2",
  className,
  play,
}: {
  lines: ReactNode[];
  as?: "h1" | "h2" | "h3";
  className?: string;
  /** Controlled mode (hero): reveal when true instead of on scroll. */
  play?: boolean;
}) {
  const MotionSpan = motion.span;
  return (
    <Tag className={className}>
      {lines.map((line, i) => (
        <span className="reveal-line" key={i}>
          <MotionSpan
            initial={{ y: "115%", rotate: 2 }}
            {...(play === undefined
              ? { whileInView: { y: "0%", rotate: 0 }, viewport: { once: true, margin: "0px 0px -8% 0px" } }
              : { animate: play ? { y: "0%", rotate: 0 } : { y: "115%", rotate: 2 } })}
            transition={{ duration: 1.25, delay: 0.08 * i, ease: EASE }}
          >
            {line}
          </MotionSpan>
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

export const ArrowIcon = ({ color = "#2bf59a" }: { color?: string }) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2 7h10M8 3l4 4-4 4" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
