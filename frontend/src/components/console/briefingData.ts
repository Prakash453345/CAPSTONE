import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Radio, ScanEye, TrafficCone, TriangleAlert, type LucideIcon } from "lucide-react";
import { edgeById, roadEdges, roadLabel, shortJunctionName } from "@/data/network";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useAnalyticsStore } from "@/store/analyticsStore";
import { useMapStore } from "@/store/mapStore";
import { ago, useNow } from "@/components/console/hooks";
import type { Tone } from "@/components/console/tone";
import { anomalyWord, incidentWord } from "@/components/console/words";
import type { EmergencyRequest } from "@/types";

/** The briefing's derived data, kept apart from its components. */

export function focusEdge(edgeId: string, zoom = 16) {
  const e = edgeById.get(edgeId);
  if (!e) return;
  const p = e.path[Math.floor(e.path.length / 2)]!;
  useMapStore.getState().focusOn({ longitude: p[0], latitude: p[1] }, zoom);
}

/** Value now vs roughly five minutes ago, from the session's samples. */
export function useTrend(pick: (s: { vehicles: number; congestion: number; speed: number | null; signals: number }) => number | null) {
  const samples = useAnalyticsStore((s) => s.samples);
  return useMemo(() => {
    const last = samples[samples.length - 1];
    if (!last) return null;
    const target = last.at - 5 * 60_000;
    const then = samples.find((s) => s.at >= target) ?? samples[0]!;
    const a = pick(then);
    const b = pick(last);
    if (a == null || b == null || then === last) return null;
    return { delta: b - a, minutes: Math.max(1, Math.round((last.at - then.at) / 60_000)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [samples]);
}


export interface AttentionItem {
  id: string;
  icon: LucideIcon;
  tone: Tone;
  title: string;
  detail: string;
  action: string;
  run: () => void;
}

export function useAttentionItems(): AttentionItem[] {
  const navigate = useNavigate();
  const now = useNow(15_000);
  const incidents = useIncidentStore((s) => s.incidents);
  const anomalies = useIncidentStore((s) => s.anomalies);
  const intersections = useIncidentStore((s) => s.intersections);
  return useMemo(() => {
    const out: AttentionItem[] = [];
    for (const i of incidents.filter((x) => x.status === "candidate")) {
      out.push({
        id: `i-${i.id}`,
        icon: ScanEye,
        tone: "warn",
        title: `Possible ${incidentWord(i.type)}, ${shortJunctionName(i.affectedIntersection ?? "")}`,
        detail: `${Math.round(i.confidence * 100)}% confidence · ${ago(Date.parse(i.detectedAt), now)}`,
        action: "Review",
        run: () => {
          useIncidentStore.getState().selectIncident(i.id);
          useMapStore.getState().focusOn(i, 17);
          navigate("/console/anomalies");
        },
      });
    }
    for (const a of anomalies.filter((x) => x.status === "active")) {
      out.push({
        id: `a-${a.id}`,
        icon: a.severity === "blocked" ? TrafficCone : TriangleAlert,
        tone: a.severity === "blocked" || a.severity === "high" ? "critical" : "warn",
        title: `${anomalyWord(a.kind)} on ${roadLabel(a.edgeId)}`,
        detail: `${Math.round(a.estimatedImpact * 100)}% of capacity lost · ${ago(Date.parse(a.startTime), now)}`,
        action: "View",
        run: () => {
          useIncidentStore.getState().selectAnomaly(a.id);
          focusEdge(a.edgeId);
          navigate("/console/anomalies");
        },
      });
    }
    for (const j of intersections.filter((x) => x.fault)) {
      out.push({
        id: `s-${j.id}`,
        icon: Radio,
        tone: "critical",
        title: `Signal fault, ${shortJunctionName(j.id)}`,
        detail: j.fault!.detail || j.fault!.faultType.replace(/_/g, " "),
        action: "Locate",
        run: () => {
          useMapStore.getState().focusOn(j, 17);
          navigate("/console/traffic");
        },
      });
    }
    return out;
  }, [incidents, anomalies, intersections, navigate, now]);
}


export function missionFacts(r: EmergencyRequest) {
  const progress = r.live?.routeProgress ?? (r.state === "completed" ? 1 : 0);
  const eta = r.live?.etaS ?? r.etaS;
  const signals = r.corridor?.reservations.length ?? r.route?.signalisedIntersections.length ?? 0;
  const cleared = r.corridor?.passedIntersections.length ?? 0;
  return { progress, eta, signals, cleared };
}


/** Roads grouped by street, worst segment first. */
export function useBusiestRoads(limit = 5) {
  const congestion = useTrafficStore((s) => s.roadCongestion);
  return useMemo(() => {
    const byStreet = new Map<string, { name: string; value: number; edgeId: string; km: number; count: number }>();
    for (const e of roadEdges) {
      const v = congestion[e.id];
      if (v == null) continue;
      const name = roadLabel(e);
      const cur = byStreet.get(name);
      if (!cur) byStreet.set(name, { name, value: v, edgeId: e.id, km: e.lengthM / 1000, count: 1 });
      else {
        cur.km += e.lengthM / 1000;
        cur.count++;
        if (v > cur.value) {
          cur.value = v;
          cur.edgeId = e.id;
        }
      }
    }
    return [...byStreet.values()].sort((a, b) => b.value - a.value).slice(0, limit);
  }, [congestion, limit]);
}

