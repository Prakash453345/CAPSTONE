import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Siren,
  TrafficCone,
} from "lucide-react";
import { networkName, roadLabel } from "@/data/network";
import { useSystemStore } from "@/store/systemStore";
import { useAnalyticsStore } from "@/store/analyticsStore";
import { useNotificationStore } from "@/store/notificationStore";
import { useEmergencyStore } from "@/store/emergencyStore";
import { AnimatedNumber, Button, Dot, EmptyState, Meter, Panel, PanelHeader, Pill } from "@/components/console/kit";
import { listMotion } from "@/components/console/motion";
import { ago, useNow } from "@/components/console/hooks";
import { toneBg, toneText, type Tone } from "@/components/console/tone";
import {
  congestionTone,
  congestionWord,
  mmss,
  networkMood,
  STATE_WORDS,
  unitName,
} from "@/components/console/words";
import { cn } from "@/utils/cn";
import { focusEdge, missionFacts, useAttentionItems, useBusiestRoads, useTrend } from "@/components/console/briefingData";
import type { EmergencyRequest } from "@/types";

// ------------------------------------------------------------ network status

export function NetworkStatus() {
  const summary = useSystemStore((s) => s.summary);
  const samples = useAnalyticsStore((s) => s.samples);
  const has = summary.lastUpdate !== null;
  const latest = samples[samples.length - 1];
  const mood = networkMood(has ? summary.congestion : null);
  const tVehicles = useTrend((s) => s.vehicles);
  const tSpeed = useTrend((s) => s.speed);
  const tCong = useTrend((s) => s.congestion);

  return (
    <Panel className="overflow-hidden">
      <div className="px-5 pb-4 pt-5">
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Dot tone={mood.tone} pulse={has} />
          {networkName}, now
        </div>
        <motion.p
          key={mood.headline}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-2 text-[21px] font-semibold leading-snug tracking-[-0.02em] text-foreground"
        >
          {mood.headline}
        </motion.p>
      </div>
      <dl className="grid grid-cols-2 border-t border-border">
        <Stat
          label="Average speed"
          value={latest?.speed ?? null}
          unit="km/h"
          format={(v) => v.toFixed(1)}
          trend={tSpeed}
          goodWhenUp
        />
        <Stat
          label="Congestion"
          value={has ? summary.congestion * 100 : null}
          unit="%"
          trend={tCong}
          className="border-l border-border"
        />
        <Stat label="Vehicles" value={has ? summary.vehicleCount : null} trend={tVehicles} neutral className="border-t border-border" />
        <Stat
          label="Signals reporting"
          value={has ? summary.signalsOnline : null}
          unit={`of ${summary.signalsTotal || 7}`}
          className="border-l border-t border-border"
        />
      </dl>
    </Panel>
  );
}

function Stat({
  label,
  value,
  unit,
  format,
  trend,
  goodWhenUp = false,
  neutral = false,
  className,
}: {
  label: string;
  value: number | null;
  unit?: string;
  format?: (v: number) => string;
  trend?: { delta: number; minutes: number } | null;
  goodWhenUp?: boolean;
  neutral?: boolean;
  className?: string;
}) {
  let tone: Tone = "neutral";
  if (trend && Math.abs(trend.delta) >= 0.5 && !neutral) {
    const up = trend.delta > 0;
    tone = up === goodWhenUp ? "ok" : "warn";
  }
  const Arrow = trend && trend.delta < 0 ? ArrowDownRight : ArrowUpRight;
  return (
    <div className={cn("px-5 py-4", className)}>
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd>
        <span className="mt-1 flex items-baseline gap-1.5">
          <AnimatedNumber value={value} format={format} className="text-[22px] font-semibold tracking-[-0.02em] text-foreground" />
          {unit && <span className="text-[13px] text-muted-foreground">{unit}</span>}
        </span>
        <span className="mt-1 block h-4 text-[12px]">
          {trend && Math.abs(trend.delta) >= 0.05 ? (
            <span className={cn("inline-flex items-center gap-0.5", toneText(tone))}>
              <Arrow className="size-3.5" />
              {Math.abs(trend.delta) >= 10 ? Math.round(Math.abs(trend.delta)) : Math.abs(trend.delta).toFixed(1)} in {trend.minutes} min
            </span>
          ) : (
            <span className="text-muted-foreground">Steady</span>
          )}
        </span>
      </dd>
    </div>
  );
}

// ------------------------------------------------------------ attention

export function AttentionList({ limit = 5 }: { limit?: number }) {
  const items = useAttentionItems();
  const navigate = useNavigate();
  return (
    <Panel>
      <PanelHeader
        title="Needs your attention"
        subtitle={items.length ? `${items.length} ${items.length === 1 ? "item" : "items"}` : undefined}
        actions={
          items.length > limit ? (
            <Button variant="ghost" size="sm" onClick={() => navigate("/console/anomalies")}>
              See all
            </Button>
          ) : undefined
        }
      />
      {items.length === 0 ? (
        <div className="flex items-center gap-3 px-5 pb-5">
          <span className="grid size-9 place-items-center rounded-xl bg-status-ok-muted text-status-ok">
            <CheckCircle2 className="size-[18px]" />
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">All clear</p>
            <p className="text-[13px] text-muted-foreground">Nothing needs you right now.</p>
          </div>
        </div>
      ) : (
        <motion.ul variants={listMotion.container} initial="hidden" animate="show" className="px-2 pb-2">
          {items.slice(0, limit).map((it) => (
            <motion.li key={it.id} variants={listMotion.item}>
              <button
                type="button"
                onClick={it.run}
                className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted"
              >
                <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", toneBg(it.tone), toneText(it.tone))}>
                  <it.icon className="size-[17px]" strokeWidth={1.9} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 block text-[13.5px] font-medium leading-snug text-foreground">{it.title}</span>
                  <span className="block truncate text-[12.5px] text-muted-foreground">{it.detail}</span>
                </span>
                <span className="flex items-center gap-1 text-[12.5px] font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                  {it.action}
                  <ArrowRight className="size-3.5" />
                </span>
              </button>
            </motion.li>
          ))}
        </motion.ul>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------ missions

export function MissionCard({ request, onOpen, compact = false }: { request: EmergencyRequest; onOpen?: () => void; compact?: boolean }) {
  const { progress, eta, signals, cleared } = missionFacts(request);
  const state = STATE_WORDS[request.state];
  return (
    <div className={cn("rounded-2xl", !compact && "p-5")}>
      <div className="flex items-start gap-3">
        <span className="relative grid size-11 shrink-0 place-items-center rounded-2xl bg-status-critical-muted text-status-critical">
          <Siren className="size-5" strokeWidth={1.9} />
          {request.state === "in_transit" && <span className="absolute -right-0.5 -top-0.5 size-3 animate-pulse rounded-full bg-status-critical ring-2 ring-surface" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-[15px] font-semibold text-foreground">{unitName(request.vehicleId)}</p>
            <Pill tone={state.tone} dot>
              {state.label}
            </Pill>
          </div>
          <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
            {roadLabel(request.sourceEdge)} to {roadLabel(request.destinationEdge)}
          </p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Fact label="Arrives in" value={mmss(eta)} />
        <Fact label="Signals cleared" value={signals ? `${cleared} of ${signals}` : "–"} />
        <Fact label="Route" value={`${Math.round(progress * 100)}%`} />
      </div>
      <Meter value={progress} tone="ok" className="mt-3" />
      {onOpen && (
        <Button variant="secondary" size="sm" className="mt-4 w-full" onClick={onOpen}>
          Follow on the map
          <ArrowRight className="size-3.5" />
        </Button>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[12px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-[15px] font-semibold text-foreground tabular">{value}</p>
    </div>
  );
}

export function ActiveMissions({ requests }: { requests: EmergencyRequest[] }) {
  const navigate = useNavigate();
  const select = useEmergencyStore((s) => s.selectRequest);
  if (!requests.length) return null;
  const [first, ...rest] = requests;
  return (
    <Panel>
      <PanelHeader title="Emergency in progress" subtitle={requests.length > 1 ? `${requests.length} units on the road` : undefined} />
      <div className="px-5 pb-5">
        <MissionCard
          compact
          request={first!}
          onOpen={() => {
            select(first!.id);
            navigate("/console/emergency");
          }}
        />
        {rest.length > 0 && (
          <p className="mt-3 text-[12.5px] text-muted-foreground">
            And {rest.map((r) => unitName(r.vehicleId)).join(", ")}.
          </p>
        )}
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------ roads

export function BusiestRoads() {
  const roads = useBusiestRoads(5);
  const navigate = useNavigate();
  return (
    <Panel>
      <PanelHeader
        title="Busiest streets"
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate("/console/traffic")}>
            All roads
          </Button>
        }
      />
      {roads.length === 0 ? (
        <EmptyState icon={TrafficCone} title="No road readings yet" className="py-6" />
      ) : (
        <ul className="px-2 pb-2">
          {roads.map((r) => {
            const tone = congestionTone(r.value);
            return (
              <li key={r.name}>
                <button
                  type="button"
                  onClick={() => focusEdge(r.edgeId)}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-muted"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[13.5px] font-medium text-foreground">{r.name}</span>
                      <span className={cn("shrink-0 text-[12.5px] font-medium tabular", toneText(tone))}>
                        {congestionWord(r.value)} · {Math.round(r.value * 100)}%
                      </span>
                    </span>
                    <Meter value={r.value} tone={tone} className="mt-2" />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------ recent

const TONE_FOR: Record<string, Tone> = { critical: "critical", warn: "warn", info: "info", ok: "ok" };

export function RecentEvents({ limit = 5 }: { limit?: number }) {
  const items = useNotificationStore((s) => s.items);
  const now = useNow(15_000);
  if (!items.length) return null;
  return (
    <Panel>
      <PanelHeader title="Recent" />
      <ol className="relative px-5 pb-5">
        <span className="absolute bottom-6 left-[27px] top-1 w-px bg-border" aria-hidden />
        {items.slice(0, limit).map((n) => (
          <li key={n.id} className="relative flex gap-3 py-1.5">
            <span className="relative z-10 mt-1.5 grid size-[15px] shrink-0 place-items-center rounded-full bg-surface">
              <Dot tone={TONE_FOR[n.tone] ?? "neutral"} />
            </span>
            <div className="min-w-0">
              <p className="text-[13px] font-medium text-foreground">{n.title}</p>
              <p className="text-[12.5px] text-muted-foreground">
                {n.message} · {ago(n.atMs, now)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
