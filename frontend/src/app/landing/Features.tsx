import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { AnimatePresence, motion, useInView } from "framer-motion";
import { Lines, Reveal } from "./motion";
import type { JunctionState, Scene3D } from "./city3d/scenes";
import { AMBER as A, BLUE as C, GREEN as G, RED as R } from "./palette";
import "./showcase.css";
import { hasFastWebGL } from "@/utils/webgl";

const EASE = [0.16, 1, 0.3, 1] as const;

// ------------------------------------------------------------ icons

const Ico = ({ children }: { children: ReactNode }) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);
const SignalIcon = () => (
  <Ico>
    <rect x="8" y="2.5" width="8" height="19" rx="4" />
    <circle cx="12" cy="7" r="1.4" />
    <circle cx="12" cy="12" r="1.4" />
    <circle cx="12" cy="17" r="1.4" />
  </Ico>
);
const CameraIcon = () => (
  <Ico>
    <path d="M3 7.5h11a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H3z" />
    <path d="M16 11l5-3v8l-5-3" />
  </Ico>
);
const RouteIcon = () => (
  <Ico>
    <circle cx="5" cy="18" r="2.2" />
    <circle cx="19" cy="6" r="2.2" />
    <path d="M7 18h5a3 3 0 0 0 3-3V9a3 3 0 0 1 3-3" />
  </Ico>
);
const LogIcon = () => (
  <Ico>
    <path d="M8 6h12M8 12h12M8 18h12" />
    <circle cx="4" cy="6" r="1" />
    <circle cx="4" cy="12" r="1" />
    <circle cx="4" cy="18" r="1" />
  </Ico>
);

// ------------------------------------------------------------ live 3D scenes

type Scenes = typeof import("./city3d/scenes");
type Make = (s: Scenes, canvas: HTMLCanvasElement, overlay: HTMLCanvasElement, reduced: boolean) => Scene3D;

/** A 3D scene that runs while it is on screen. three.js is fetched on first use. */
function Live({ make, reduced, className }: { make: Make; reduced: boolean; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const makeRef = useRef(make);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const canvas = ref.current;
    const overlay = overlayRef.current;
    if (!canvas || !overlay) return;
    let scene: Scene3D | null = null;
    let cancelled = false;
    let visible = false;
    const sync = () => scene?.setRunning(visible && !document.hidden);
    import("./city3d/scenes")
      .then((mod) => {
        if (cancelled || !hasFastWebGL()) return;
        scene = makeRef.current(mod, canvas, overlay, reduced);
        setReady(true);
        sync();
      })
      .catch(() => {});
    const io = new IntersectionObserver(([e]) => {
      visible = !!e?.isIntersecting;
      sync();
    });
    io.observe(canvas);
    document.addEventListener("visibilitychange", sync);
    return () => {
      cancelled = true;
      io.disconnect();
      document.removeEventListener("visibilitychange", sync);
      scene?.dispose();
    };
  }, [reduced]);
  return (
    <>
      <canvas ref={ref} className={`ft-3d ${ready ? "ready" : ""} ${className ?? ""}`} aria-hidden="true" />
      <canvas ref={overlayRef} className="ft-overlay" aria-hidden="true" />
    </>
  );
}

// ------------------------------------------------------------ 1. adaptive signals

function SignalsScene({ reduced }: { reduced: boolean }) {
  const [st, setSt] = useState<JunctionState>({ waiting: [0, 0], green: [14, 7], active: -1, left: 0 });
  const make = useCallback<Make>((s, c, _o, r) => s.createJunction(c, r, setSt), []);
  const total = st.green[0] + st.green[1];
  const rows = [
    { name: "Main road", n: st.waiting[0], g: st.green[0] },
    { name: "Side road", n: st.waiting[1], g: st.green[1] },
  ];
  return (
    <>
      <div className="ft-view">
        <Live make={make} reduced={reduced} />
      </div>
      <div className="ft-panel">
        <div className="ft-panel-h">
          <b>Green time, planned from the queue</b>
          <small>Live at this junction</small>
        </div>
        <div className="ft-split">
          {rows.map((r, i) => (
            <div key={r.name} className={st.active === i ? "on" : ""}>
              <span>
                {r.name}
                <em>
                  {r.n} {r.n === 1 ? "vehicle" : "vehicles"} waiting
                </em>
              </span>
              <b>{st.active === i ? `${Math.ceil(st.left)} s left` : `${r.g} s`}</b>
              <i style={{ "--w": `${(r.g / total) * 100}%`, "--c": st.active === i ? G : "#8b95a5" } as CSSProperties} />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------------------ 2. incident detection

const makeCctv: Make = (s, c, o, r) => s.createCctv(c, o, r);
const makeCorridor: Make = (s, c, o, r) => s.createCorridorLoop(c, o, r);

function Clock() {
  const [t, setT] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setT(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <>{t.toLocaleTimeString("en-GB", { hour12: false })}</>;
}

function DetectScene({ reduced }: { reduced: boolean }) {
  return (
    <>
      <div className="ft-view">
        <Live make={makeCctv} reduced={reduced} className="cctv" />
        <div className="ft-hud ft-hud-l">
          <i /> CAM 07 BANDAR ROAD
        </div>
        <div className="ft-hud ft-hud-r">
          <Clock />
        </div>
      </div>
      <div className="ft-panel ft-alert">
        <span className="ft-alert-ico">!</span>
        <span className="ft-alert-txt">
          <b>Possible breakdown, sent to the control room</b>
          <small>A person checks the video before anything happens.</small>
        </span>
        <span className="ft-alert-btns">
          <span className="yes">Confirm</span>
          <span>Dismiss</span>
        </span>
      </div>
    </>
  );
}

// ------------------------------------------------------------ 3. green corridor

function CorridorScene({ reduced }: { reduced: boolean }) {
  return (
    <>
      <div className="ft-view">
        <Live make={makeCorridor} reduced={reduced} />
      </div>
      <div className="ft-panel">
        <div className="ft-panel-h">
          <b>Every light on its route turns green</b>
          <small>and goes back to normal once it has passed</small>
        </div>
        <div className="ft-legend">
          <span>
            <i style={{ background: G }} /> Held green for the ambulance
          </span>
          <span>
            <i style={{ background: R }} /> Normal cycle for cross traffic
          </span>
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------------------ 4. audit trail

const LOG: [string, string, string, "Automatic" | "Operator"][] = [
  ["21:04:07", "Accident spotted by camera 07", R, "Automatic"],
  ["21:04:22", "Confirmed on live video", A, "Operator"],
  ["21:04:23", "Nearest ambulance sent", C, "Automatic"],
  ["21:04:24", "Lights on the route held green in turn", G, "Automatic"],
  ["21:04:39", "Unsafe manual change blocked", A, "Automatic"],
  ["21:04:57", "Ambulance on scene, all lights back to normal", G, "Automatic"],
];

function AuditScene(_: { reduced: boolean }) {
  return (
    <>
      <div className="ft-log">
        <div className="ft-log-h">
          <span>
            <b>Incident #0412</b>
            <small>Bandar Road, 3 Oct, 21:04</small>
          </span>
          <span className="ft-saved">
            <i /> Saved automatically
          </span>
        </div>
        <ol>
          {LOG.map(([t, text, col, who], i) => (
            <li key={t} style={{ "--c": col, animationDelay: `${0.15 + i * 0.22}s` } as CSSProperties}>
              <i />
              <time>{t}</time>
              <span>{text}</span>
              <em className={who === "Operator" ? "op" : ""}>{who}</em>
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}

// ------------------------------------------------------------ the showcase

const FEATURES = [
  {
    key: "signals",
    title: "Smarter traffic lights",
    body: "Each light counts the cars waiting and gives the busier road more green time, instead of running the same fixed timer all day.",
    color: C,
    Icon: SignalIcon,
    Scene: SignalsScene,
  },
  {
    key: "detect",
    title: "Automatic accident alerts",
    body: "Existing street cameras notice a crash or a stopped car within seconds and alert the control room, often before anyone calls.",
    color: C,
    Icon: CameraIcon,
    Scene: DetectScene,
  },
  {
    key: "corridor",
    title: "A green path for ambulances",
    body: "Lights along the ambulance's route turn green just before it arrives, then go straight back to normal for everyone else.",
    color: C,
    Icon: RouteIcon,
    Scene: CorridorScene,
  },
  {
    key: "audit",
    title: "A record of every decision",
    body: "Every alert, approval and signal change is saved in order: who did it, when, and why. Anything can be reviewed later.",
    color: C,
    Icon: LogIcon,
    Scene: AuditScene,
  },
] as const;

const DWELL = 7; // seconds per feature while auto-playing

export function Features({ reduced }: { reduced: boolean }) {
  const [active, setActive] = useState(0);
  const [hold, setHold] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const inView = useInView(rootRef, { margin: "-20% 0px -20% 0px" });
  const auto = !reduced && inView && !hold;
  const f = FEATURES[active]!;
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  // the timer bar's own animation drives auto-advance, so pausing it on hover pauses both
  const next = () => setActive((a) => (a + 1) % FEATURES.length);

  useEffect(() => {
    if (!inView) setHold(false);
  }, [inView]);

  const onKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + FEATURES.length) % FEATURES.length;
    setActive(n);
    tabs.current[n]?.focus();
  };

  return (
    <section className="block" id="modules">
      <div className="wrap">
        <div className="shead">
          <Lines className="h2" lines={["Lights, cameras and ambulances", "on one live map."]} />
          <Reveal delay={0.1}>
            <p className="lede">
              Signal control, accident detection, ambulance routing and the incident log all read the same picture
              of the city, so one event moves all four at once.
            </p>
          </Reveal>
        </div>

        <Reveal>
          <div
            className={`ft ${auto ? "playing" : ""}`}
            ref={rootRef}
            style={{ "--c": f.color } as CSSProperties}
            onMouseEnter={() => setHold(true)}
            onMouseLeave={() => setHold(false)}
          >
            <div className="ft-tabs">
              <div className="ft-tablist" role="tablist" aria-label="Features">
              {FEATURES.map((x, i) => (
                <button
                  key={x.key}
                  ref={(el) => (tabs.current[i] = el)}
                  role="tab"
                  id={`ft-tab-${x.key}`}
                  aria-selected={i === active}
                  aria-controls="ft-stage"
                  tabIndex={i === active ? 0 : -1}
                  className={`ft-tab ${i === active ? "on" : ""}`}
                  style={{ "--c": x.color } as CSSProperties}
                  onClick={() => setActive(i)}
                  onKeyDown={(e) => onKey(e, i)}
                >
                  <span className="ft-ico">
                    <x.Icon />
                  </span>
                  <span className="ft-txt">
                    <b>{x.title}</b>
                    <span className="ft-more">
                      <span>{x.body}</span>
                    </span>
                  </span>
                  {i === active && (
                    <span className="ft-timer" aria-hidden="true">
                      <i key={active} style={{ animationDuration: `${DWELL}s` }} onAnimationEnd={() => auto && next()} />
                    </span>
                  )}
                </button>
              ))}
              </div>
              <a className="ft-cta" href="/console">
                See all four together in the live demo
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
            </div>

            <div className="ft-stage" id="ft-stage" role="tabpanel" aria-labelledby={`ft-tab-${f.key}`}>
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={f.key}
                  className="ft-scene"
                  initial={reduced ? false : { opacity: 0, scale: 1.03 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={reduced ? undefined : { opacity: 0, scale: 0.99 }}
                  transition={{ duration: 0.55, ease: EASE }}
                >
                  <f.Scene reduced={reduced} />
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
