import { useRef, useState } from "react";
import { motion, type MotionValue, useMotionValueEvent, useScroll, useTransform } from "framer-motion";
import { ArrowIcon } from "./motion";

/**
 * The closing act: a full-size signal head that cycles red → red+amber →
 * green as you scroll, and only on green does the way into the demo open.
 */
export function Finale() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const red = useTransform(p, [0, 0.34, 0.44], [1, 1, 0]);
  const amber = useTransform(p, [0.2, 0.26, 0.4, 0.46], [0, 1, 1, 0]);
  const green = useTransform(p, [0.42, 0.5], [0, 1]);
  // A restrained halo that sits on the signal itself, not a wash over the page.
  const glow = useTransform(
    p,
    [0, 0.3, 0.42, 0.5],
    [
      "radial-gradient(18% 34% at 14% 50%, rgba(255,59,48,.09), transparent 70%)",
      "radial-gradient(18% 34% at 14% 50%, rgba(255,59,48,.09), transparent 70%)",
      "radial-gradient(18% 34% at 14% 50%, rgba(255,176,32,.08), transparent 70%)",
      "radial-gradient(18% 34% at 14% 62%, rgba(43,245,154,.09), transparent 70%)",
    ],
  );
  const waitO = useTransform(p, [0.38, 0.46], [1, 0]);
  const goO = useTransform(p, [0.46, 0.56], [0, 1]);
  const goY = useTransform(p, [0.46, 0.6], [40, 0]);
  const [go, setGo] = useState(false);
  useMotionValueEvent(p, "change", (v) => setGo(v > 0.47));

  return (
    <section className="finale" id="go" ref={ref}>
      <div className="finale-stick">
        <motion.div className="finale-glow" style={{ background: glow }} />
        <div className="finale-inner">
          <BigSignal red={red} amber={amber} green={green} />
          <div style={{ position: "relative" }}>
            <motion.div style={{ opacity: waitO }} aria-hidden={go}>
              <div className="state is-red">Red: the ambulance waits</div>
              <h2>
                Every red light
                <br />
                <span className="dim">costs precious seconds.</span>
              </h2>
              <p className="hint">Keep scrolling to turn this one green.</p>
            </motion.div>
            <motion.div
              style={{ opacity: goO, y: goY, position: "absolute", inset: 0, pointerEvents: go ? "auto" : "none" }}
              aria-hidden={!go}
            >
              <div className="state is-green">Green: the road is clear</div>
              <h2>
                Now see it
                <br />
                <em className="hl-green">in action.</em>
              </h2>
              <p>
                Report an accident yourself, watch a person confirm it, see the ambulance get sent, and watch the
                traffic lights turn green ahead of it, live.
              </p>
              <div className="ctas">
                <a className="btn" href="/console" tabIndex={go ? 0 : -1}>
                  <span className="lamp">
                    <ArrowIcon />
                  </span>
                  Try the live demo
                </a>
                <a className="btn ghost" href="#flow" tabIndex={go ? 0 : -1}>
                  See how it works
                </a>
              </div>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}

function BigSignal({ red, amber, green }: { red: MotionValue<number>; amber: MotionValue<number>; green: MotionValue<number> }) {
  // the bloom is kept to about half strength so the lamp glows without flooding the section
  const soft = (v: number) => v * 0.55;
  const lamps: [number, string, string, MotionValue<number>, MotionValue<number>][] = [
    [90, "#ff3b30", "#3a0a08", red, useTransform(red, soft)],
    [230, "#ffb020", "#3a2606", amber, useTransform(amber, soft)],
    [370, "#2bf59a", "#063a24", green, useTransform(green, soft)],
  ];
  return (
    <svg className="bigsig" viewBox="0 0 180 560" aria-hidden="true">
      <defs>
        <linearGradient id="bs-body" x1="0" x2="1">
          <stop offset="0" stopColor="#0a0c10" />
          <stop offset=".45" stopColor="#1a1e25" />
          <stop offset="1" stopColor="#08090c" />
        </linearGradient>
        <filter id="bs-bloom" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="16" />
        </filter>
        {lamps.map(([, lit], i) => (
          <radialGradient key={i} id={`bs-lens${i}`} cx="50%" cy="42%" r="55%">
            <stop offset="0" stopColor="#fff" stopOpacity=".95" />
            <stop offset=".18" stopColor={lit} />
            <stop offset="1" stopColor={lit} stopOpacity=".55" />
          </radialGradient>
        ))}
        <pattern id="bs-fresnel" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.3" fill="rgba(255,255,255,.12)" />
        </pattern>
      </defs>
      {/* backplate */}
      <rect x="4" y="6" width="172" height="460" rx="22" fill="#07080a" stroke="rgba(255,255,255,.05)" />
      <rect x="20" y="14" width="140" height="444" rx="60" fill="url(#bs-body)" stroke="rgba(255,255,255,.08)" />
      {/* pole */}
      <rect x="80" y="466" width="20" height="94" fill="url(#bs-body)" />
      {lamps.map(([cy, lit, off, on, bloom], i) => (
        <g key={cy}>
          <motion.circle cx="90" cy={cy} r="58" fill={lit} filter="url(#bs-bloom)" style={{ opacity: bloom }} />
          <circle cx="90" cy={cy} r="50" fill="#040506" />
          <circle cx="90" cy={cy} r="44" fill={off} />
          <motion.circle cx="90" cy={cy} r="44" fill={`url(#bs-lens${i})`} style={{ opacity: on }} />
          <circle cx="90" cy={cy} r="44" fill="url(#bs-fresnel)" />
          {/* visor */}
          <path d={`M36 ${cy - 30} Q90 ${cy - 86} 144 ${cy - 30} L150 ${cy - 44} Q90 ${cy - 104} 30 ${cy - 44}Z`} fill="#0b0d11" />
          <ellipse cx="74" cy={cy - 18} rx="14" ry="7" fill="rgba(255,255,255,.1)" transform={`rotate(-30 74 ${cy - 18})`} />
        </g>
      ))}
    </svg>
  );
}
