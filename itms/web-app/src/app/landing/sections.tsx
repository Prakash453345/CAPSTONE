import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useAccessLabel } from "./useAccess";
import { AnimatePresence, animate, motion, useInView, useScroll } from "framer-motion";
import { ArrowIcon, Lines, Reveal, ScrubWord } from "./motion";

const EASE = [0.16, 1, 0.3, 1] as const;
const cssVar = (name: string, value: string) => ({ [name]: value }) as CSSProperties;

// ------------------------------------------------------------ LED ticker

const TICKER: [string, string][] = [
  ["Accidents spotted in seconds", "#ff3b30"],
  ["A real person checks every alert", "#ffb020"],
  ["The nearest ambulance is sent", "#3fe0ff"],
  ["Traffic lights ahead turn green", "#2bf59a"],
  ["Roads go back to normal right after", "#2bf59a"],
  ["Every decision is recorded", "#ffb020"],
];

export function Ticker() {
  const items = [...TICKER, ...TICKER];
  return (
    <div className="ticker" aria-hidden="true">
      <div className="ticker-track">
        {items.map(([t, c], i) => (
          <span key={i} className="item">
            <i style={cssVar("--c", c)} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------ manifesto

const MANIFESTO =
  "Technology should help people decide, never decide for them. Our system can confirm a broken-down car on its own, but *a *real *person *always checks anything that involves someone's life.";

export function Manifesto() {
  const ref = useRef<HTMLParagraphElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.45"] });
  const words = MANIFESTO.split(" ");
  return (
    <section className="block manifesto" id="why">
      <div className="wrap">
        <Reveal>
          <span className="eyebrow">Our promise</span>
        </Reveal>
        <p className="big" ref={ref}>
          {words.map((w, i) => {
            const hl = w.startsWith("*");
            return (
              <ScrubWord
                key={i}
                progress={scrollYProgress}
                range={[i / words.length, (i + 1) / words.length]}
                className={hl ? "hl" : ""}
              >
                {hl ? w.slice(1) : w}
              </ScrubWord>
            );
          })}
        </p>
        <Reveal delay={0.1}>
          <div className="sign">
            <span className="shield">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M9 2l6 3v4c0 3.4-2.4 6.2-6 7-3.6-.8-6-3.6-6-7V5l6-3z" stroke="#ffb020" strokeWidth="1.4" strokeLinejoin="round" />
              </svg>
            </span>
            <span>
              <b>People stay in charge</b>An ambulance is sent only after a person says yes
            </span>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ capabilities

const CAPS: [string, string][] = [
  ["Keeps working if something fails", "Lights fall back to safe, normal timing on their own"],
  ["Never acts alone on people", "Anything involving a person is checked by a human first"],
  ["No gridlock from emergencies", "Only a safe number of green paths can run at once"],
  ["Fastest route, not shortest", "Routes use live traffic, not just distance on a map"],
  ["Fair to everyone else", "Lights go back to normal the moment the ambulance passes"],
  ["Nothing is hidden", "Every decision is saved, approved or turned down"],
  ["Look back at any moment", "See exactly what happened, when, and why"],
];

function MiniSignal() {
  return (
    <span className="minisig" aria-hidden="true">
      <i style={cssVar("--c", "#ff3b30")} />
      <i style={cssVar("--c", "#ffb020")} />
      <i style={cssVar("--c", "#2bf59a")} />
    </span>
  );
}

/** A reliability row whose little signal cycles red → amber → green once it scrolls in. */
function CapRow({ name, desc, i }: { name: string; desc: string; i: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -18% 0px" });
  const [lamp, setLamp] = useState(0);
  useEffect(() => {
    if (!inView) return;
    const t1 = window.setTimeout(() => setLamp(1), 500 + i * 90);
    const t2 = window.setTimeout(() => setLamp(2), 1100 + i * 90);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [inView, i]);
  return (
    <motion.div
      ref={ref}
      className="caprow"
      data-lamp={lamp}
      initial={{ opacity: 0, x: 30 }}
      whileInView={{ opacity: 1, x: 0 }}
      viewport={{ once: true, margin: "0px 0px -8% 0px" }}
      transition={{ duration: 0.9, delay: i * 0.05, ease: EASE }}
    >
      <span className="ix">{String(i + 1).padStart(2, "0")}</span>
      <div>
        <h4>{name}</h4>
        <p>{desc}</p>
      </div>
      <MiniSignal />
    </motion.div>
  );
}

export function Capabilities() {
  return (
    <section className="block" id="capabilities" style={{ paddingTop: 0 }}>
      <div className="wrap caps">
        <div className="sticky">
          <Reveal>
            <span className="eyebrow">Reliability</span>
          </Reveal>
          <Lines className="h2" lines={[<span className="dim">Built to be</span>, "trusted."]} />
          <Reveal delay={0.1}>
            <p className="lede" style={{ marginTop: 22, maxWidth: "38ch" }}>
              When lives are involved, "usually works" isn't good enough. Each of these exists to prevent a real problem
              on the road.
            </p>
            <div className="chips">
              {["Always on", "Human-approved", "Privacy-first", "Ready to grow"].map((c) => (
                <span className="chip" key={c}>
                  {c}
                </span>
              ))}
            </div>
          </Reveal>
        </div>
        <div>
          {CAPS.map(([name, desc], i) => (
            <CapRow key={name} name={name} desc={desc} i={i} />
          ))}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ metrics

function Count({
  to,
  prefix = "",
  suffix = "",
  decimals = 0,
}: {
  to: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -15% 0px" });
  useEffect(() => {
    if (!inView || !ref.current) return;
    const el = ref.current;
    const c = animate(0, to, {
      duration: 1.8,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => (el.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`),
    });
    return () => c.stop();
  }, [inView, to, prefix, suffix, decimals]);
  return (
    <b ref={ref}>
      {prefix}0{suffix}
    </b>
  );
}

export function Metrics() {
  const mets = [
    { to: 20, label: "Junctions in the live pilot", tag: "Today", c: "#2bf59a" },
    { to: 1, suffix: "s", label: "How often the live map updates", tag: "Real-time", c: "#3fe0ff" },
    { to: 0.5, prefix: "<", suffix: "s", decimals: 1, label: "For a traffic light to respond", tag: "Target", c: "#ffb020" },
    { to: 24, suffix: "/7", label: "Watching the roads", tag: "Always on", c: "#2bf59a" },
  ];
  return (
    <section className="block" id="scale" style={{ paddingTop: 0 }}>
      <div className="wrap">
        <Reveal y={50}>
          <div className="metrics">
            <div className="grid-bg" />
            <span className="eyebrow">By the numbers</span>
            <h2 className="h2" style={{ marginTop: 22, position: "relative" }}>
              <span className="dim">Built for one city.</span>
              <br />
              Ready for many.
            </h2>
            <p className="lede" style={{ maxWidth: "52ch", marginTop: 22, position: "relative" }}>
              Designed to grow from a handful of junctions to an entire city without changing how it makes
              decisions.
            </p>
            <div className="mets">
              {mets.map((m) => (
                <div className="met" key={m.label}>
                  <Count to={m.to} prefix={m.prefix} suffix={m.suffix} decimals={m.decimals} />
                  <span>{m.label}</span>
                  <em style={cssVar("--c", m.c)}>{m.tag}</em>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ faq

const FAQ: [string, string][] = [
  [
    "What happens if part of the system fails during rush hour?",
    "The system is built to fail safely. If the smart signal control ever goes offline, intersections automatically fall back to reliable pre-set timing, so traffic never stops moving because of it. The same principle applies everywhere: if a camera feed is lost, detection relies on other data it already has; if data delivery slows down, routine updates are the first thing deprioritized, never anything related to an active incident.",
  ],
  [
    "Can an operator override a signal whenever they want?",
    "No, and that's intentional. Every signal has a minimum time it must stay green before it can be changed, and an active emergency route always outranks a manual request. If a request is denied, the operator is told exactly why and when they can try again. It never just fails silently. Every request, approved or denied, is logged for accountability.",
  ],
  [
    "Why test in a simulated environment first?",
    "Because it lets us prove the system works before it ever touches real infrastructure. The simulation behaves like a live city feed, so we can stress-test it, train it and refine it safely, then connect it to real cameras and sensors with confidence, without changing anything about how the system itself makes decisions.",
  ],
  [
    "How are two emergencies wanting the same junction resolved?",
    "If the requests don't conflict, both are simply granted. If they do, priority goes first to the more serious emergency, then to whichever route is already underway, then to whichever vehicle is closer. The lower-priority vehicle is rerouted if a good alternative exists. Otherwise it still gets a boost, just a shorter one, instead of a full corridor. There's also a limit on how many routes can be cleared at once, so the system never creates gridlock while trying to prevent it.",
  ],
  [
    "What stops this from becoming a surveillance system?",
    "A firm rule built into how it works: cameras can automatically confirm traffic problems like a stalled vehicle, debris or an obstruction, but anything involving a person always goes to a human for review before any action is taken. That does mean a slightly slower response on that class of event, and it's a trade-off we made deliberately, to protect people's privacy.",
  ],
];

export function Faq() {
  const access = useAccessLabel();
  const [open, setOpen] = useState(0);
  return (
    <section className="block" id="faq" style={{ paddingTop: 0 }}>
      <div className="wrap">
        <div className="shead">
          <div>
            <Reveal>
              <span className="eyebrow">FAQ</span>
            </Reveal>
            <Lines className="h2" lines={["Your questions,", <span className="dim">answered.</span>]} />
          </div>
        </div>
        <div className="faqgrid">
          <Reveal>
            <div>
              {FAQ.map(([q, a], i) => {
                const isOpen = open === i;
                return (
                  <div className={`fq ${isOpen ? "open" : ""}`} key={q}>
                    <button className="fqb" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? -1 : i)}>
                      <span className="n">{String(i + 1).padStart(2, "0")}</span>
                      <span className="q">{q}</span>
                      <span className="lamp3" aria-hidden="true">
                        <i style={cssVar("--c", "#ff3b30")} />
                        <i style={cssVar("--c", "#ffb020")} />
                        <i style={cssVar("--c", "#2bf59a")} />
                      </span>
                    </button>
                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.div
                          className="fqa"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.6, ease: EASE }}
                        >
                          <p>{a}</p>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </div>
          </Reveal>
          <Reveal delay={0.12} className="askcol">
            <aside className="askcard">
              <span className="eyebrow">Still not sure?</span>
              <h3>
                See it for yourself.
              </h3>
              <p>Trigger an incident, watch it get verified and dispatched, and see traffic signals respond in real time.</p>
              <a className="btn" href="/console">
                <span className="lamp">
                  <ArrowIcon />
                </span>
                {access}
              </a>
            </aside>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ footer

export function Footer() {
  const access = useAccessLabel();
  return (
    <footer>
      <div className="wrap">
        <div className="fgrid">
          <div>
            <div className="kin">
              Let's{" "}
              <span className="rot">
                <span>
                  <i>detect</i>
                  <i>dispatch</i>
                  <i>clear</i>
                  <i>detect</i>
                </span>
              </span>
              <br />
              the road ahead.
            </div>
            <p style={{ fontSize: 14.5, maxWidth: "34ch" }}>
              Intelligent Traffic Management &amp; Emergency Response Platform, piloted in Vijayawada.
            </p>
          </div>
          <div>
            <h5>Platform</h5>
            <a href="#modules">Modules</a>
            <a href="#flow">How it responds</a>
            <a href="#faq">FAQ</a>
          </div>
          <div>
            <h5>Our commitments</h5>
            <span>Human oversight</span>
            <span>Full audit trail</span>
            <span>Privacy by design</span>
            <span>Built to scale</span>
          </div>
          <div>
            <h5>Access</h5>
            <a href="/console">{access}</a>
            <Link to="/drive">Crew view</Link>
            <span>Citizen app (coming soon)</span>
            <span>Field mobile app (coming soon)</span>
          </div>
        </div>
        <div className="wm" aria-hidden="true">
          ITMS
        </div>
        <div className="fbot">
          <span>© 2026 Intelligent Traffic Management Platform</span>
          <span>Some figures reflect target performance at full-city scale</span>
        </div>
      </div>
    </footer>
  );
}
