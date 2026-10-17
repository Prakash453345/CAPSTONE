import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useAccessLabel } from "./useAccess";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "framer-motion";

const cssVar = (name: string, value: string) => ({ [name]: value }) as CSSProperties;

// ------------------------------------------------------------ intro

/**
 * A three-second cold open: one signal head counts down red → red+amber →
 * green, and the green floods out into the hero. Shown once per session;
 * any click or key skips it.
 */
export function Intro({ onDone }: { onDone: () => void }) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>[] = [];
    // Start the countdown only once the main thread is free again (the hero
    // compiles its shaders behind the intro), so the sequence never stutters.
    let r2 = 0;
    const r1 = requestAnimationFrame(() => {
      r2 = requestAnimationFrame(() => {
        t = [
          setTimeout(() => setStage(1), 200),
          setTimeout(() => setStage(2), 1000),
          setTimeout(() => setStage(3), 1650),
          setTimeout(onDone, 2300),
        ];
      });
    });
    const skip = () => onDone();
    window.addEventListener("keydown", skip);
    return () => {
      cancelAnimationFrame(r1);
      cancelAnimationFrame(r2);
      t.forEach(clearTimeout);
      window.removeEventListener("keydown", skip);
    };
  }, [onDone]);

  return (
    <motion.div
      className="intro"
      onClick={onDone}
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 1.1, ease: [0.65, 0, 0.35, 1] } }}
      role="presentation"
    >
      <motion.div
        aria-hidden="true"
        style={{
          position: "absolute",
          width: 120,
          height: 120,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(43,245,154,.55), rgba(43,245,154,0) 70%)",
          pointerEvents: "none",
        }}
        initial={{ scale: 0, opacity: 0 }}
        animate={stage >= 3 ? { scale: 26, opacity: [0, 0.9, 0.25] } : {}}
        transition={{ duration: 1.3, ease: [0.16, 1, 0.3, 1] }}
      />
      <motion.div
        className="intro-sig"
        initial={{ opacity: 0, y: 14, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        exit={{ scale: 1.2, opacity: 0 }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      >
        <div className="intro-house" aria-hidden="true">
          <i className={stage >= 1 && stage < 3 ? "on" : ""} style={cssVar("--c", "#ff3b30")} />
          <i className={stage === 2 ? "on" : ""} style={cssVar("--c", "#ffb020")} />
          <i className={stage >= 3 ? "on" : ""} style={cssVar("--c", "#2bf59a")} />
        </div>
        <div className="intro-meta">
          <b>ITMS</b>
          <span>{stage >= 3 ? "Road clear" : stage === 2 ? "Clearing the way" : "Accident reported"}</span>
        </div>
      </motion.div>
      <span className="intro-skip">Click to skip</span>
    </motion.div>
  );
}

export function IntroGate({ show, onDone }: { show: boolean; onDone: () => void }) {
  return <AnimatePresence>{show && <Intro onDone={onDone} />}</AnimatePresence>;
}

// ------------------------------------------------------------ nav

export function Nav({ ready }: { ready: boolean }) {
  const access = useAccessLabel();
  const { scrollYProgress, scrollY } = useScroll();
  const [lamp, setLamp] = useState(0);
  const [solid, setSolid] = useState(false);
  useMotionValueEvent(scrollYProgress, "change", (v) => setLamp(v < 0.34 ? 0 : v < 0.67 ? 1 : 2));
  useMotionValueEvent(scrollY, "change", (v) => setSolid(v > 40));
  return (
    <motion.nav
      className={`nav ${solid ? "solid" : ""}`}
      initial={{ opacity: 0, y: -20, x: "-50%" }}
      animate={ready ? { opacity: 1, y: 0, x: "-50%" } : { opacity: 0, y: -20, x: "-50%" }}
      transition={{ duration: 1, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
      aria-label="Main"
    >
      <a className="brand" href="#top" aria-label="ITMS, back to top">
        <span className="navsig" aria-hidden="true">
          <i className={lamp === 0 ? "on" : ""} style={cssVar("--c", "#ff3b30")} />
          <i className={lamp === 1 ? "on" : ""} style={cssVar("--c", "#ffb020")} />
          <i className={lamp === 2 ? "on" : ""} style={cssVar("--c", "#2bf59a")} />
        </span>
        ITMS
      </a>
      <div className="links">
        <a href="#flow">How it works</a>
        <a href="#modules">Features</a>
        <a href="#faq">FAQ</a>
      </div>
      <Link className="go" to="/login">
        {access}
      </Link>
    </motion.nav>
  );
}

// ------------------------------------------------------------ signal rail

const RAIL = [
  ["top", "Arrival"],
  ["why", "Our promise"],
  ["flow", "How it works"],
  ["modules", "Features"],
  ["capabilities", "Reliability"],
  ["scale", "Scale"],
  ["faq", "FAQ"],
  ["go", "Go"],
] as const;

/** Section progress as a column of signals: passed sections go green. */
export function Rail({ ready }: { ready: boolean }) {
  const { scrollY } = useScroll();
  const [active, setActive] = useState(0);
  useMotionValueEvent(scrollY, "change", (y) => {
    const probe = y + window.innerHeight * 0.45;
    let idx = 0;
    RAIL.forEach(([id], i) => {
      const el = document.getElementById(id);
      if (el && el.getBoundingClientRect().top + y <= probe) idx = i;
    });
    setActive((a) => (a === idx ? a : idx));
  });
  return (
    <motion.nav
      className="rail"
      aria-label="Sections"
      initial={{ opacity: 0 }}
      animate={{ opacity: ready ? 1 : 0 }}
      transition={{ duration: 1, delay: 1 }}
    >
      {RAIL.map(([id, label], i) => (
        <a key={id} href={`#${id}`} className={i < active ? "past" : i === active ? "now" : ""} aria-current={i === active ? "true" : undefined}>
          <span>{label}</span>
        </a>
      ))}
    </motion.nav>
  );
}

// ------------------------------------------------------------ floating dock

/** On screen while the pinned story (id="flow") holds the viewport. */
function inPinned(id: string) {
  const r = document.getElementById(id)?.getBoundingClientRect();
  return !!r && r.top < window.innerHeight * 0.5 && r.bottom > window.innerHeight * 0.5;
}

/** A small floating call-to-action that appears once the hero is behind you.
 * It keeps out of the reader's way: it slips away while scrolling down, comes
 * back on the way up, and steps aside where the page already offers the same
 * button or a pinned scene needs the whole screen. */
export function FloatingDock() {
  const access = useAccessLabel();
  const { scrollY } = useScroll();
  const [show, setShow] = useState(false);
  const last = useRef({ y: 0, up: false });
  useMotionValueEvent(scrollY, "change", (y) => {
    const dy = y - last.current.y;
    if (Math.abs(dy) > 4) last.current = { y, up: dy < 0 };
    const hero = document.getElementById("top");
    const go = document.getElementById("go");
    const pastHero = !!hero && y > hero.offsetTop + hero.offsetHeight - window.innerHeight * 0.6;
    const r = go?.getBoundingClientRect();
    const inFinale = !!r && r.top < window.innerHeight && r.bottom > 0;
    const next = pastHero && !inFinale && !inPinned("flow") && last.current.up;
    setShow((s) => (s === next ? s : next));
  });
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="fdock"
          initial={{ opacity: 0, y: 30, x: "-50%" }}
          animate={{ opacity: 1, y: 0, x: "-50%" }}
          exit={{ opacity: 0, y: 30, x: "-50%" }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <span>See it working for yourself</span>
          <a className="go" href="/console">
            {access}
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M2 7h10M8 3l4 4-4 4" stroke="#04120b" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
