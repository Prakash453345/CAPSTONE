import { useEffect, useRef, useState } from "react";
import { motion, useMotionValueEvent, useScroll, useTransform } from "framer-motion";
import type { HeroScene } from "./heroScene";
import { ChevronIcon, Lines } from "./motion";
import { useAccessLabel } from "./useAccess";
import { hasFastWebGL } from "@/utils/webgl";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Full-bleed WebGL night avenue, pinned for two screens. Scrolling lifts the
 * camera to an aerial view while the copy hands over from the problem ("an
 * ambulance should never meet a red light") to the answer.
 */
export function Hero({ paused, reduced }: { paused: boolean; reduced: boolean }) {
  const access = useAccessLabel();
  const sectionRef = useRef<HTMLElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HeroScene | null>(null);
  const sync = useRef<() => void>(() => {});
  const pausedRef = useRef(paused);
  const [webgl, setWebgl] = useState(true);

  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start start", "end end"] });

  useEffect(() => {
    const host = hostRef.current;
    const section = sectionRef.current;
    if (!host || !section) return;
    // three.js is fetched after first paint so it stays out of the page's first download
    let scene: HeroScene | null = null;
    let cancelled = false;
    let visible = true;
    sync.current = () => {
      scene?.setRunning(visible && !document.hidden && !pausedRef.current && !reduced);
      if (reduced) scene?.renderOnce();
    };
    const io = new IntersectionObserver(([e]) => {
      visible = !!e?.isIntersecting;
      sync.current();
    });
    io.observe(section);
    document.addEventListener("visibilitychange", sync.current);
    import("./heroScene")
      .then(({ HeroScene }) => {
        if (cancelled) return;
        if (!hasFastWebGL()) throw new Error("no GPU: showing the still hero");
        scene = new HeroScene(host, { reducedMotion: reduced, mobile: window.innerWidth < 760 });
        sceneRef.current = scene;
        scene.setProgress(scrollYProgress.get() / 0.82);
        sync.current();
      })
      .catch(() => {
        if (!cancelled) setWebgl(false);
      });
    return () => {
      cancelled = true;
      io.disconnect();
      document.removeEventListener("visibilitychange", sync.current);
      scene?.dispose();
      sceneRef.current = null;
    };
    // the scene is built once per motion preference
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced]);

  useEffect(() => {
    pausedRef.current = paused;
    sync.current();
  }, [paused]);

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    sceneRef.current?.setProgress(v / 0.82);
    if (reduced) sceneRef.current?.renderOnce();
  });

  const aOpacity = useTransform(scrollYProgress, [0, 0.22], [1, 0]);
  const aY = useTransform(scrollYProgress, [0, 0.22], [0, -70]);
  const aEvents = useTransform(scrollYProgress, (v) => (v > 0.12 ? "none" : "auto"));
  const bOpacity = useTransform(scrollYProgress, [0.36, 0.52], [0, 1]);
  const bY = useTransform(scrollYProgress, [0.36, 0.56], [50, 0]);

  return (
    <section className="hero" id="top" ref={sectionRef}>
      <div className="hero-stick">
        <div className="hero-canvas" ref={hostRef} aria-hidden="true" data-webgl={webgl ? "1" : "0"} />
        <div className="hero-shade" />

        <motion.div className="hero-copy a" style={{ opacity: aOpacity, y: aY, pointerEvents: aEvents }}>
          <div className="wrap">
            <div className="inner">
              <motion.p
                className="eyebrow"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, ease: EASE }}
              >
                Emergency-aware traffic control for Vijayawada
              </motion.p>
              <Lines
                as="h1"
                play
                lines={[
                  "An ambulance should",
                  "never meet",
                  <>
                    a <em className="hl-red">red light.</em>
                  </>,
                ]}
              />
              <motion.p
                className="lede"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.9, delay: 0.35, ease: EASE }}
              >
                Traffix watches the city&rsquo;s existing cameras for accidents, asks an operator to confirm what it
                sees, sends the nearest ambulance and turns each light on its route green just before it arrives.
              </motion.p>
              <motion.div
                className="ctas"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.9, delay: 0.5, ease: EASE }}
              >
                <a className="btn" href="/console">
                  {access}
                </a>
                <a className="more" href="#flow">
                  See how it works <ChevronIcon />
                </a>
              </motion.div>
              <motion.ul
                className="trust"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 1, delay: 0.7 }}
              >
                <li>An operator approves every dispatch</li>
                <li>Uses the cameras already on the street</li>
                <li>Every decision is logged</li>
              </motion.ul>
            </div>
          </div>
        </motion.div>

        <motion.div className="hero-copy b" style={{ opacity: bOpacity, y: bY }}>
          <div className="wrap">
            <div className="inner">
              <p className="eyebrow">What Traffix does</p>
              <h2 className="hero-h">
                So we turn
                <br />
                every one <em className="hl-green">green.</em>
              </h2>
              <p className="lede">
                As the ambulance gets close, each traffic light ahead of it turns green just in time, then goes back
                to normal the moment it has passed. Everyone else barely notices.
              </p>
            </div>
          </div>
        </motion.div>

      </div>
    </section>
  );
}
