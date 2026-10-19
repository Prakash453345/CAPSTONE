import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { WifiOff } from "lucide-react";
import { CrewMap } from "@/components/crew/CrewMap";
import { CrewHeader } from "@/components/crew/CrewHeader";
import { ManeuverBanner } from "@/components/crew/ManeuverBanner";
import { CorridorCard } from "@/components/crew/CorridorCard";
import { HazardsCard } from "@/components/crew/HazardsCard";
import { TripBar } from "@/components/crew/TripBar";
import { ArrivalCard, BriefingCard, DirectionsCard, NoVehicleCard, StandbyCard } from "@/components/crew/MissionCards";
import { unitName } from "@/components/console/words";
import { HOME_CITY } from "@/data/city";
import { useGuidanceVoice } from "@/crew/useGuidanceVoice";
import { useMission } from "@/crew/useMission";
import { useNewCallAlert } from "@/crew/useNewCallAlert";
import { useWakeLock } from "@/crew/useWakeLock";
import { TrafficDataBridge } from "@/services/traffic/TrafficDataBridge";
import { trafficAdvice } from "@/services/weather/weather";
import { useAuthStore } from "@/store/authStore";
import { useCrewStore } from "@/store/crewStore";
import { useEmergencyStore } from "@/store/emergencyStore";
import { useSystemStore } from "@/store/systemStore";
import { useEffectiveWeather, useWeatherStore } from "@/store/weatherStore";

/**
 * Crew page: what an emergency-vehicle crew follows. It shows the route the
 * system chose, the next turn, which signals are being held green for them,
 * and what is on the road ahead. It reads the same live data as the operator
 * console, so what the dispatcher sees and what the crew sees agree.
 */
export function CrewPage() {
  const user = useAuthStore((s) => s.user);
  // A crew account is tied to its own vehicle, so it cannot look at anyone
  // else's. Operators choose any unit.
  const locked = user?.role === "responder";
  const chosenUnit = useCrewStore((s) => s.unitId);
  const unitId = locked ? (user?.unitId ?? null) : chosenUnit;
  const setUnit = useCrewStore((s) => s.setUnit);
  const voice = useCrewStore((s) => s.voice);
  const setVoice = useCrewStore((s) => s.setVoice);
  const { request, mission, units } = useMission(unitId);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const connection = useSystemStore((s) => s.connectionStatus);
  const lastUpdate = useSystemStore((s) => s.summary.lastUpdate);
  const weather = useEffectiveWeather();

  const [showDirections, setShowDirections] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  // Which offered route is being looked at; a new call starts on the recommended one.
  const [preview, setPreview] = useState(0);
  useEffect(() => setPreview(0), [request?.id]);

  useEffect(() => {
    // Restore on unmount, like MapPage: without this the console kept showing
    // "Crew - TRAFFIX" in the tab after a visit here, which reads as the crew
    // page still being open when it isn't.
    const previous = document.title;
    document.title = "Crew · TRAFFIX";
    return () => {
      document.title = previous;
    };
  }, []);

  // Weather changes how fast a crew can safely go, so keep it fresh.
  useEffect(() => {
    const run = () => void useWeatherStore.getState().refresh(HOME_CITY.center.latitude, HOME_CITY.center.longitude);
    run();
    const t = window.setInterval(run, 10 * 60_000);
    return () => window.clearInterval(t);
  }, []);

  // Nobody has chosen a vehicle yet: follow the first one that has a call.
  useEffect(() => {
    if (!locked && !unitId) {
      const busy = units.find((u) => u.active);
      if (busy) setUnit(busy.id);
    }
  }, [locked, unitId, units, setUnit]);

  // The map's emergency layer draws the selected request's vehicle larger.
  useEffect(() => {
    selectRequest(request?.id ?? null);
    return () => selectRequest(null);
  }, [request?.id, selectRequest]);

  const guiding = Boolean(mission?.plan && mission.underway && !mission.arrived);
  useWakeLock(guiding);
  useGuidanceVoice(mission, voice);
  useNewCallAlert(request, voice);

  const name = unitId ? (units.find((u) => u.id === unitId)?.name ?? unitName(unitId)) : null;
  const finished = Boolean(mission && (mission.arrived || mission.request.state === "completed" || mission.request.state === "cancelled"));
  const showArrival = finished && mission && dismissed !== mission.request.id;
  const stale = connection === "reconnecting" || connection === "offline";

  // Which set of cards is showing: changing it cross-fades them (opacity only,
  // so nothing slides) instead of swapping them in a single frame.
  let view: string;
  let body;
  if (locked && !unitId) {
    view = "novehicle";
    body = <NoVehicleCard />;
  } else if (!mission || (finished && !showArrival)) {
    view = "standby";
    body = <StandbyCard unitName={name} weatherAdvice={weather ? trafficAdvice(weather) : null} />;
  } else if (showArrival) {
    view = "arrival";
    body = <ArrivalCard mission={mission} onDone={() => setDismissed(mission.request.id)} />;
  } else if (showDirections && mission.plan) {
    view = "directions";
    body = <DirectionsCard mission={mission} onClose={() => setShowDirections(false)} />;
  } else if (guiding) {
    view = "guiding";
    body = (
      <>
        <CorridorCard signals={mission.signals} corridor={mission.corridor} />
        <HazardsCard hazards={mission.hazards} advice={weather ? trafficAdvice(weather) : null} />
      </>
    );
  } else {
    view = "briefing";
    body = <BriefingCard mission={mission} preview={Math.min(preview, mission.routes.length - 1)} onPreview={setPreview} onDirections={() => setShowDirections(true)} />;
  }
  const showBanner = Boolean(guiding && mission?.next && mission.plan && !showDirections);
  const showTrip = Boolean(mission?.plan && !finished);

  return (
    <MotionConfig reducedMotion="user">
      {/* On a wide screen: a solid panel column beside a framed map, like the
          console. On a phone: the map fills the screen and the panels float over it. */}
      <div className="relative h-full overflow-hidden bg-background text-foreground lg:grid lg:grid-cols-[432px_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
        <TrafficDataBridge />

        <div className="absolute inset-0 lg:relative lg:col-start-2 lg:row-start-1 lg:m-4 lg:ml-0 lg:overflow-hidden lg:rounded-2xl lg:shadow-elevation-1">
          <CrewMap mission={mission} preview={mission ? Math.min(preview, mission.routes.length - 1) : 0} onPreview={setPreview} />
          <AnimatePresence initial={false}>
            {showTrip && mission && (
              <motion.div
                key="trip"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                className="pointer-events-none absolute inset-x-3 bottom-3 z-10 lg:inset-x-4 lg:bottom-4"
              >
                <TripBar
                  mission={mission}
                  unitName={name ?? ""}
                  voice={voice}
                  onVoice={() => setVoice(!voice)}
                  onDirections={() => setShowDirections((v) => !v)}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {stale && (
          <div role="alert" className="pointer-events-none absolute inset-x-0 top-0 z-30 flex justify-center p-2">
            <p className="pointer-events-auto flex max-w-xl items-center gap-2 rounded-xl bg-status-critical px-4 py-2.5 text-[14px] font-medium text-white shadow-elevation-3">
              <WifiOff className="size-4 shrink-0" aria-hidden />
              Connection lost. Keep following the route on screen; positions and signals may be out of date
              {lastUpdate ? ` (last update ${new Date(lastUpdate).toLocaleTimeString()})` : ""}.
            </p>
          </div>
        )}

        <div className="pointer-events-none absolute inset-0 z-10 flex flex-col gap-3 p-3 pb-[176px] lg:pointer-events-auto lg:static lg:col-start-1 lg:row-start-1 lg:min-h-0 lg:overflow-y-auto lg:p-4 lg:pr-3">
          <CrewHeader units={withCurrent(units, unitId, name)} unitId={unitId} onUnit={setUnit} locked={locked} kind={locked ? (user?.unitKind ?? null) : null} />
          <AnimatePresence initial={false}>
            {showBanner && mission?.next && (
              <motion.div
                key="banner"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              >
                <ManeuverBanner next={mission.next} distM={mission.nextDistM} then={mission.then} offRouteM={mission.offRouteM} />
              </motion.div>
            )}
          </AnimatePresence>
          {/* Phone: leave the map visible and let the cards scroll in their own band. */}
          <div className="min-h-0 flex-1 lg:hidden" />
          <div
            role="region"
            aria-label="Route details"
            tabIndex={0}
            className="pointer-events-none flex max-h-[32vh] min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain rounded-2xl lg:pointer-events-auto lg:max-h-none lg:flex-1"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={view}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.16 }}
                className="pointer-events-none flex flex-col gap-3"
              >
                {body}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </MotionConfig>
  );
}

/** The picker must always be able to show the unit that is currently chosen. */
function withCurrent(units: ReturnType<typeof useMission>["units"], unitId: string | null, name: string | null) {
  return unitId && !units.some((u) => u.id === unitId) ? [...units, { id: unitId, name: name ?? unitId, active: false }] : units;
}
