import { useState } from "react";
import { useMotionValueEvent, useScroll } from "framer-motion";

/** The Traffix mark: a crosshair standing in for an intersection (same as the favicon). */
export function Mark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#151a26" />
      <path d="M16 6v20M6 16h20" stroke="#7b93ff" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="16" cy="16" r="3.4" fill="#151a26" stroke="#7b93ff" strokeWidth="2.5" />
    </svg>
  );
}

/**
 * A plain, full-width bar: name on the left, three in-page links, one way in.
 * Transparent over the hero, then a translucent blur once the page moves.
 */
export function Nav() {
  const { scrollY } = useScroll();
  const [solid, setSolid] = useState(false);
  useMotionValueEvent(scrollY, "change", (v) => setSolid(v > 24));
  return (
    <header className={`nav ${solid ? "solid" : ""}`}>
      <div className="wrap nav-in">
        <a className="brand" href="#top" aria-label="Traffix, back to top">
          <Mark />
          Traffix
        </a>
        <nav className="links" aria-label="Main">
          <a href="#flow">How it works</a>
          <a href="#modules">Features</a>
          <a href="#capabilities">Safety</a>
          <a href="#faq">FAQ</a>
        </nav>
        <a className="nav-cta" href="/console">
          Live demo
        </a>
      </div>
    </header>
  );
}
