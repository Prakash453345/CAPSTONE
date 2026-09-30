import { useEffect } from "react";
import { useAnalyticsStore } from "@/store/analyticsStore";
import { useMapStore } from "@/store/mapStore";
import { useSystemStore } from "@/store/systemStore";
import { useTrafficStore } from "@/store/trafficStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useEmergencyStore } from "@/store/emergencyStore";
import { useNotificationStore } from "@/store/notificationStore";
import { createTrafficProvider } from "@/services/traffic";
import { isBackendReachable } from "@/services/traffic/backendProbe";
import { classifyConnectionEvent } from "@/services/traffic/notifications";

/**
 * Headless bridge: owns the active data provider, pumps its snapshots into the
 * stores, and mirrors its connection state onto systemStore. Mounted once by
 * the app shell. Re-subscribes whenever the operator switches data mode.
 */
export function TrafficDataBridge() {
  const dataMode = useSystemStore((s) => s.dataMode);

  // Once per mount, ask whether a backend is actually there. Deliberately not
  // in the provider effect below: this decides the *initial* mode, and must
  // not re-run each time the operator switches.
  useEffect(() => {
    let cancelled = false;
    isBackendReachable().then((reachable) => {
      if (reachable && !cancelled) useSystemStore.getState().adoptLiveIfUnchosen();
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const provider = createTrafficProvider(dataMode);
    const { ingest, reset } = useTrafficStore.getState();
    const { setIncidents, setAnomalies, setIntersections } = useIncidentStore.getState();
    const { setRequests } = useEmergencyStore.getState();
    const { setConnectionStatus, applySummary } = useSystemStore.getState();
    const { push: pushNotifications } = useNotificationStore.getState();

    // Never carry demo observations or an unfinished command into a live session.
    reset();
    useIncidentStore.getState().clearReviews();
    setIncidents([]);
    setAnomalies([]);
    setIntersections([]);
    setRequests([]);
    useEmergencyStore.getState().clearDraft();
    useEmergencyStore.getState().selectRequest(null);
    useIncidentStore.getState().selectIncident(null);
    useIncidentStore.getState().selectAnomaly(null);
    useIncidentStore.getState().selectIntersection(null);
    useMapStore.getState().setSelectedVehicle(null);
    useMapStore.getState().setInteractionMode("idle");
    useAnalyticsStore.getState().reset();
    applySummary({ operational: false, vehicleCount: 0, congestion: 0,
      signalsOnline: 0, signalsTotal: 0, lastUpdate: null });

    const offSnap = provider.subscribe((snap) => {
      useAnalyticsStore.getState().ingest(snap);
      ingest({
        vehicles: snap.vehicles,
        roadCongestion: snap.roadCongestion,
      });
      setIncidents(snap.incidents);
      setAnomalies(snap.anomalies);
      setIntersections(snap.intersections);
      setRequests(snap.emergencyRequests);
      applySummary(snap.summary);
      if (snap.events.length) pushNotifications(snap.events);
    });

    // Connection health, as its own notification category — tracked here
    // (not inside a provider) so it applies uniformly to whichever one is
    // active. `wasEverOnline` stops the first cold connect from reading as
    // a "recovery".
    let prevStatus = "connecting";
    let wasEverOnline = false;
    const offStatus = provider.onStatus((status) => {
      const notif = classifyConnectionEvent(prevStatus, status, wasEverOnline, Date.now());
      if (notif) pushNotifications([notif]);
      if (status === "online") wasEverOnline = true;
      prevStatus = status;
      setConnectionStatus(status);
    });

    provider.start();

    return () => {
      offSnap();
      offStatus();
      provider.stop();
      reset();
    };
  }, [dataMode]);

  return null;
}
