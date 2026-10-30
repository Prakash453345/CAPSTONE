import { useRef, useState } from "react";
import { AnimatePresence, motion, useScroll } from "framer-motion";
import { Mark } from "./chrome";
import { Lines, Reveal, ScrubWord } from "./motion";

const EASE = [0.16, 1, 0.3, 1] as const;

// ------------------------------------------------------------ manifesto

const MANIFESTO =
  "Technology should help people decide, never decide for them. Traffix can confirm a broken-down car on its own, but a person always checks anything that involves someone\u2019s life.";

export function Manifesto() {
  const ref = useRef<HTMLParagraphElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.45"] });
  const words = MANIFESTO.split(" ");
  return (
    <section className="block manifesto" id="why">
      <div className="wrap">
        <p className="big" ref={ref}>
          {words.map((w, i) => (
            <ScrubWord key={i} progress={scrollYProgress} range={[i / words.length, (i + 1) / words.length]}>
              {w}
            </ScrubWord>
          ))}
        </p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ safety

const CAPS: [string, string][] = [
  ["Falls back to normal timing", "If smart control drops out, every junction returns to its fixed, safe plan on its own."],
  ["People decide about people", "Anything that involves a person goes to an operator before the system acts on it."],
  ["No gridlock from emergencies", "Only a safe number of green corridors can run at the same time."],
  ["Fastest route, not shortest", "Routes are planned on live traffic, not on distance alone."],
  ["Fair to cross traffic", "Each light goes back to its normal cycle as soon as the ambulance has passed."],
  ["A complete record", "Every alert, approval and signal change is saved with who, when and why, and can be replayed."],
];

export function Capabilities() {
  return (
    <section className="block" id="capabilities">
      <div className="wrap">
        <div className="shead">
          <Lines className="h2" lines={["Designed to fail safe."]} />
          <Reveal delay={0.1}>
            <p className="lede">
              When lives are involved, &ldquo;usually works&rdquo; isn&rsquo;t good enough. Each rule below exists to
              prevent a specific problem on the road.
            </p>
          </Reveal>
        </div>
        <Reveal>
          <ul className="caps">
            {CAPS.map(([name, desc]) => (
              <li key={name}>
                <h3>{name}</h3>
                <p>{desc}</p>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ metrics

const METS = [
  { value: "7", label: "Signalised junctions on the MG Road corridor model" },
  { value: "1 s", label: "Between live map updates" },
  { value: "< 0.5 s", label: "For a light to respond to a corridor request", note: "Target" },
];

export function Metrics() {
  return (
    <section className="block metrics" id="scale">
      <div className="wrap">
        <Lines className="h2" lines={["The pilot, in numbers."]} />
        <Reveal delay={0.1}>
          <p className="lede">
            Built and tested on a digital twin of Vijayawada&rsquo;s roads, so it can be proven safe before it touches
            a real signal.
          </p>
        </Reveal>
        <Reveal>
          <dl className="mets">
            {METS.map((m) => (
              <div className="met" key={m.label}>
                <dt>{m.label}</dt>
                <dd>
                  {m.value}
                  {m.note && <small>{m.note}</small>}
                </dd>
              </div>
            ))}
          </dl>
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
  const [open, setOpen] = useState(0);
  return (
    <section className="block" id="faq">
      <div className="wrap faqgrid">
        <div>
          <Lines className="h2" lines={["Questions"]} />
          <Reveal delay={0.1}>
            <p className="lede">
              What people ask most about how Traffix behaves on a real road. Something else?{" "}
              <a className="inline" href="/console">
                Try it in the demo
              </a>
              .
            </p>
          </Reveal>
        </div>
        <Reveal>
          <div>
            {FAQ.map(([q, a], i) => {
              const isOpen = open === i;
              return (
                <div className={`fq ${isOpen ? "open" : ""}`} key={q}>
                  <h3>
                    <button
                      className="fqb"
                      aria-expanded={isOpen}
                      aria-controls={`fq-${i}`}
                      onClick={() => setOpen(isOpen ? -1 : i)}
                    >
                      <span className="q">{q}</span>
                      <span className="plus" aria-hidden="true" />
                    </button>
                  </h3>
                  <AnimatePresence initial={false}>
                    {isOpen && (
                      <motion.div
                        className="fqa"
                        id={`fq-${i}`}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.4, ease: EASE }}
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
      </div>
    </section>
  );
}

// ------------------------------------------------------------ footer

export function Footer() {
  return (
    <footer>
      <div className="wrap">
        <div className="ftop">
          <div className="fbrand">
            <a className="brand" href="#top">
              <Mark />
              Traffix
            </a>
            <p>Intelligent traffic management and emergency response, designed for Vijayawada.</p>
          </div>
          <nav className="flinks" aria-label="Footer">
            <a href="#flow">How it works</a>
            <a href="#modules">Features</a>
            <a href="#capabilities">Safety</a>
            <a href="#faq">FAQ</a>
            <a href="/console">Live demo</a>
          </nav>
        </div>
        <div className="fbot">
          <span>&copy; 2026 Traffix</span>
          <span>Response-time figures are targets for a city-wide rollout, measured on the simulation.</span>
        </div>
      </div>
    </footer>
  );
}
