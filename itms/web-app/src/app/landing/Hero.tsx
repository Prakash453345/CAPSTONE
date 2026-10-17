import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useAccessLabel } from "./useAccess";
import { motion, useMotionValueEvent, useScroll, useTransform } from "framer-motion";
import type { HeroScene } from "./heroScene";
import { ArrowIcon, Lines } from "./motion";

const EASE = [0.16, 1, 0.3, 1] as const;
const cssVar = (name: string, value: string) => ({ [name]: value }) as CSSProperties;

/**
 * Full-bleed WebGL night avenue, pinned for two screens. Scrolling lifts the
 * camera to an aerial view while the copy hands over from the problem ("an
 * ambulance should never meet a red light") to the answer.
 */
export function Hero({ ready, paused, reduced }: { ready: boolean; paused: boolean; reduced: boolean }) {
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
  const cueOpacity = useTransform(scrollYProgress, [0, 0.06], [1, 0]);

  return (
    <section className="hero" id="top" ref={sectionRef}>
      <div className="hero-stick">
        <div className="hero-canvas" ref={hostRef} aria-hidden="true" data-webgl={webgl ? "1" : "0"} />
        <div className="hero-shade" />

        <motion.div className="hero-copy a" style={{ opacity: aOpacity, y: aY, pointerEvents: aEvents }}>
          <div className="wrap">
            <div className="inner">
              <motion.span
                className="pill"
                initial={{ opacity: 0, y: 16 }}
                animate={ready ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 1, ease: EASE }}
              >
                <i className="dot" /> Now live as a pilot in Vijayawada
              </motion.span>
              <Lines
                as="h1"
                play={ready}
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
                initial={{ opacity: 0, y: 20 }}
                animate={ready ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 1.1, delay: 0.45, ease: EASE }}
              >
                ITMS is a smart traffic system for cities. It spots accidents on its own, has a real person confirm
                them, sends the nearest ambulance and turns the traffic lights ahead of it green, so help arrives
                faster.
              </motion.p>
              <motion.div
                className="ctas"
                initial={{ opacity: 0, y: 20 }}
                animate={ready ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 1.1, delay: 0.6, ease: EASE }}
              >
                <a className="btn" href="/console">
                  <span className="lamp">
                    <ArrowIcon />
                  </span>
                  {access}
                </a>
                <a className="btn ghost" href="#flow">
                  See how it works
                </a>
              </motion.div>
              <motion.ul
                className="trust"
                initial={{ opacity: 0 }}
                animate={ready ? { opacity: 1 } : {}}
                transition={{ duration: 1.2, delay: 0.85 }}
              >
                <li>
                  <i style={cssVar("--c", "#2bf59a")} /> A person approves every alert
                </li>
                <li>
                  <i style={cssVar("--c", "#3fe0ff")} /> Works with existing city cameras
                </li>
                <li>
                  <i style={cssVar("--c", "#ffb020")} /> Every decision recorded
                </li>
              </motion.ul>
            </div>
          </div>
        </motion.div>

        <motion.div className="hero-copy b" style={{ opacity: bOpacity, y: bY }}>
          <div className="wrap">
            <div className="inner">
              <span className="eyebrow">Our answer</span>
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

        <motion.a href="#why" className="scrollcue" style={{ opacity: cueOpacity }}>
          <span className="track" />
          Scroll
        </motion.a>
      </div>
    </section>
  );
}
