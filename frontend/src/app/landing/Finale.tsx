import { useEffect, useRef, useState } from "react";
import { motion, useInView } from "framer-motion";
import { AMBER, GREEN, RED } from "./palette";
import { ChevronIcon } from "./motion";
import { useAccessLabel } from "./useAccess";

type Lamp = 0 | 1 | 2;

/**
 * The closing section: a signal head that changes red → amber → green once
 * as it comes into view, beside the way into the demo. The button is there
 * from the start; the signal is only a picture of what the demo does.
 */
export function Finale({ reduced }: { reduced: boolean }) {
  const access = useAccessLabel();
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -30% 0px" });
  const [lamp, setLamp] = useState<Lamp>(reduced ? 2 : 0);
  useEffect(() => {
    if (!inView || reduced) return;
    const t = [window.setTimeout(() => setLamp(1), 700), window.setTimeout(() => setLamp(2), 1400)];
    return () => t.forEach(window.clearTimeout);
  }, [inView, reduced]);

  return (
    <section className="block finale" id="go" ref={ref}>
      <div className="wrap finale-inner">
        <BigSignal lamp={lamp} />
        <div>
          <h2 className="h2">Run an incident yourself.</h2>
          <p className="lede">
            Report an accident in the demo, confirm it as the operator, send an ambulance and watch each light on its
            route turn green ahead of it. Nothing to install.
          </p>
          <div className="ctas">
            <a className="btn" href="/console">
              {access}
            </a>
            <a className="more" href="#flow">
              Replay how it works <ChevronIcon />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function BigSignal({ lamp }: { lamp: Lamp }) {
  const lamps: [number, string, string][] = [
    [90, RED, "#3a0f0c"],
    [230, AMBER, "#3a2808"],
    [370, GREEN, "#0b3a24"],
  ];
  return (
    <svg className="bigsig" viewBox="0 0 180 560" role="img" aria-label="A traffic signal changing to green">
      <defs>
        <linearGradient id="bs-body" x1="0" x2="1">
          <stop offset="0" stopColor="#0c0f14" />
          <stop offset=".45" stopColor="#1b2029" />
          <stop offset="1" stopColor="#0a0c10" />
        </linearGradient>
        <filter id="bs-bloom" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="16" />
        </filter>
        {lamps.map(([, lit], i) => (
          <radialGradient key={i} id={`bs-lens${i}`} cx="50%" cy="42%" r="55%">
            <stop offset="0" stopColor="#fff" stopOpacity=".9" />
            <stop offset=".2" stopColor={lit} />
            <stop offset="1" stopColor={lit} stopOpacity=".6" />
          </radialGradient>
        ))}
      </defs>
      <rect x="20" y="14" width="140" height="444" rx="60" fill="url(#bs-body)" stroke="rgba(255,255,255,.08)" />
      <rect x="80" y="458" width="20" height="102" fill="url(#bs-body)" />
      {lamps.map(([cy, lit, off], i) => (
        <g key={cy}>
          <motion.circle
            cx="90"
            cy={cy}
            r="58"
            fill={lit}
            filter="url(#bs-bloom)"
            initial={false}
            animate={{ opacity: lamp === i ? 0.45 : 0 }}
            transition={{ duration: 0.35 }}
          />
          <circle cx="90" cy={cy} r="50" fill="#050608" />
          <circle cx="90" cy={cy} r="44" fill={off} />
          <motion.circle
            cx="90"
            cy={cy}
            r="44"
            fill={`url(#bs-lens${i})`}
            initial={false}
            animate={{ opacity: lamp === i ? 1 : 0 }}
            transition={{ duration: 0.35 }}
          />
          <path
            d={`M36 ${cy - 30} Q90 ${cy - 86} 144 ${cy - 30} L150 ${cy - 44} Q90 ${cy - 104} 30 ${cy - 44}Z`}
            fill="#0d1015"
          />
        </g>
      ))}
    </svg>
  );
}
