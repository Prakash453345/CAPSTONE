import { useEffect, useRef, useState, type CSSProperties } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "framer-motion";
import type { StoryScene } from "./city3d/scenes";
import { AMBER, BLUE, GREEN, RED } from "./palette";
import "./showcase.css";
import { hasFastWebGL } from "@/utils/webgl";

const EASE = [0.16, 1, 0.3, 1] as const;

const STEPS = [
  {
    key: "detect",
    t: "0:00",
    title: "Spot the problem",
    color: RED,
    body: "Street cameras notice a crash or a broken-down car within seconds, often before anyone calls it in.",
  },
  {
    key: "confirm",
    t: "0:15",
    title: "A person checks it",
    color: AMBER,
    body: "An operator looks at the live video and confirms it's real. Nothing happens without a person's OK.",
  },
  {
    key: "dispatch",
    t: "0:16",
    title: "Send help",
    color: BLUE,
    body: "The nearest free ambulance is sent on the fastest route, based on how busy the roads are right now.",
  },
  {
    key: "clear",
    t: "0:50",
    title: "Clear the way",
    color: GREEN,
    body: "Each traffic light ahead turns green just before the ambulance arrives, then goes straight back to normal.",
  },
] as const;

/** What the incident window reports at each moment of the story. */
const EVENTS = [
  { title: "Broken-down car detected", sub: "Camera 07, Bandar Road", color: RED },
  { title: "Confirmed by an operator", sub: "Checked on live video", color: AMBER },
  { title: "Ambulance on its way", sub: "Nearest free unit, by the fastest route", color: BLUE },
  { title: "Green corridor active", sub: "Lights turn green just ahead of it", color: GREEN },
  { title: "On scene in 50 seconds", sub: "Every light back to its normal cycle", color: GREEN },
] as const;

// story progress at which each step begins (matches the phases in cityScenes)
const STARTS = [0, 0.22, 0.42, 0.62, 0.96];

/** Seconds since the breakdown. The drive is about 280 m at 30 km/h in traffic. */
function clockAt(s: number) {
  if (s < 0.22) return (s / 0.22) * 9;
  if (s < 0.42) return 9 + ((s - 0.22) / 0.2) * 6;
  if (s < 0.62) return 15 + ((s - 0.42) / 0.2) * 1;
  return Math.min(50, 16 + ((s - 0.62) / 0.32) * 34);
}

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

const Check = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2.5 6.2l2.3 2.3 4.7-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * The pinned "how it works" story. Scrolling plays one incident end to end
 * inside a live-incident window, with the four steps listed beside it.
 */
export function Corridor({ paused, reduced }: { paused: boolean; reduced: boolean }) {
  const sectionRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<StoryScene | null>(null);
  const clockRef = useRef<HTMLElement>(null);
  const stepsRef = useRef<HTMLOListElement>(null);
  const segsRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  const sync = useRef<() => void>(() => {});
  const [event, setEvent] = useState(0);

  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start start", "end end"] });

  useEffect(() => {
    const canvas = canvasRef.current;
    const overlay = overlayRef.current;
    const section = sectionRef.current;
    if (!canvas || !overlay || !section) return;
    let visible = false;
    let cancelled = false;
    let loading = false;
    sync.current = () => mapRef.current?.setRunning(visible && !document.hidden && !pausedRef.current);
    // the 3D city is fetched and built as the section approaches, not on page load
    const load = () => {
      if (loading) return;
      loading = true;
      import("./city3d/scenes")
        .then(({ createStory }) => {
          if (cancelled || !hasFastWebGL()) return;
          const map = createStory(canvas, overlay, reduced);
          mapRef.current = map;
          map.setStory(scrollYProgress.get());
          sync.current();
        })
        .catch(() => {});
    };
    const near = new IntersectionObserver(([e]) => e?.isIntersecting && load(), { rootMargin: "150% 0px" });
    near.observe(section);
    const io = new IntersectionObserver(([e]) => {
      visible = !!e?.isIntersecting;
      sync.current();
    });
    io.observe(section);
    document.addEventListener("visibilitychange", sync.current);
    return () => {
      cancelled = true;
      near.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", sync.current);
      mapRef.current?.dispose();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced]);

  useEffect(() => {
    pausedRef.current = paused;
    sync.current();
  }, [paused]);

  // progress inside each step, written straight to CSS variables (no re-render per frame)
  const paint = (v: number) => {
    const fill = (el: Element, k: number) => {
      const a = STARTS[k]!;
      const b = k === 3 ? 0.94 : STARTS[k + 1]!;
      (el as HTMLElement).style.setProperty("--p", String(Math.min(1, Math.max(0, (v - a) / (b - a)))));
    };
    stepsRef.current?.querySelectorAll(".hw-step").forEach(fill);
    segsRef.current?.querySelectorAll("i").forEach(fill);
    if (clockRef.current) clockRef.current.textContent = mmss(Math.round(clockAt(v)));
  };

  useEffect(() => paint(scrollYProgress.get()), [scrollYProgress]);

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    mapRef.current?.setStory(v);
    let i = 0;
    for (let k = 0; k < STARTS.length; k++) if (v >= STARTS[k]!) i = k;
    setEvent((prev) => (prev === i ? prev : i));
    paint(v);
  });

  const step = Math.min(event, 3);
  const ev = EVENTS[event]!;

  return (
    <section className="corridor" id="flow" ref={sectionRef} aria-label="How Traffix responds to an incident">
      <div className="corridor-stick">
        <div className="hw">
          <div className="hw-side">
            <p className="eyebrow">How it works</p>
            <h2 className="hw-h">
              From a breakdown to help on scene in under a minute.
            </h2>
            <p className="hw-lede">Keep scrolling to follow one incident as it happens.</p>
            <ol className="hw-steps" ref={stepsRef}>
              {STEPS.map((s, i) => (
                <li
                  key={s.key}
                  className={`hw-step ${i === step ? "on" : i < step ? "done" : ""}`}
                  style={{ "--c": s.color } as CSSProperties}
                >
                  <span className="hw-num">{i < step || event === 4 ? <Check /> : String(i + 1).padStart(2, "0")}</span>
                  <div className="hw-body">
                    <div className="hw-row">
                      <h4>{s.title}</h4>
                      <time>{s.t}</time>
                    </div>
                    <div className="hw-more">
                      <p>{s.body}</p>
                    </div>
                  </div>
                  <i className="hw-prog" />
                </li>
              ))}
            </ol>
          </div>

          <div className="hw-window" style={{ "--c": ev.color } as CSSProperties}>
            <div className="hw-bar">
              <span className="hw-live">
                <i /> Live incident
              </span>
              <span className="hw-loc">Bandar Road, Vijayawada</span>
              <span className="hw-clock">
                <small>Since the accident</small>
                <b ref={clockRef}>0:00</b>
              </span>
            </div>
            <div className="hw-map">
              <canvas ref={canvasRef} aria-hidden="true" />
              <canvas ref={overlayRef} className="hw-overlay" aria-hidden="true" />
              <div className="hw-vignette" />
            </div>
            <div className="hw-foot">
              <div className="hw-status">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={event}
                    className="hw-toast"
                    role="status"
                    initial={reduced ? false : { opacity: 0, y: 18, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={reduced ? undefined : { opacity: 0, y: -10, scale: 0.98 }}
                    transition={{ duration: 0.5, ease: EASE }}
                    style={{ "--c": ev.color } as CSSProperties}
                  >
                    <span className="hw-toast-ico" />
                    <span>
                      <b>{ev.title}</b>
                      <small>{ev.sub}</small>
                    </span>
                  </motion.div>
                </AnimatePresence>
              </div>
              <div className="hw-segs" ref={segsRef} aria-hidden="true">
                {STEPS.map((s) => (
                  <i key={s.key} style={{ "--c": s.color } as CSSProperties} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
