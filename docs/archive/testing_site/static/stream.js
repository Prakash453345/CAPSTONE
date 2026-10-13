/* The WebSocket client and the reduction of the event stream into state.

   The browser talks to `api-service` directly on ws://<host>:8000/v1/stream --
   it is the same socket the repo's own console uses, so anything wrong here is
   wrong there too, which is the point of a test harness.

   Vehicle positions are one event per vehicle per tick. At heavy demand that is
   hundreds a second, so they update the vehicle map but never enter the event
   ring; the ring is for the events you actually read. */

import { S, markDirty, isAnomalyActive, isEmergencyOpen } from './state.js';

const RING = 1600;
const VEHICLE_TTL_MS = 4000;

let ws = null;
let retryTimer = null;
let closedByUs = false;

const CATEGORY = {
  VehiclePositionUpdated: 'veh',
  ApproachState: 'veh',
  SystemHeartbeat: '',
  SignalChanged: 'sig',
  SignalFaulted: 'sig',
  AnomalyUpdated: 'anom',
  EmergencyRequestUpdated: 'emrg',
  EmergencyVehicleUpdated: 'emrg',
  GreenCorridorUpdated: 'corr',
  IncidentCandidate: 'inc',
  IncidentDetected: 'inc',
  IncidentUpdated: 'inc',
};

export function wsUrl() {
  const port = S.boot?.config?.api_port || 8000;
  return `ws://${location.hostname || '127.0.0.1'}:${port}/v1/stream`;
}

export function connect() {
  closedByUs = false;
  clearTimeout(retryTimer);
  const url = wsUrl();
  S.ws.url = url;
  S.ws.state = 'connecting';
  markDirty('pills');

  try {
    ws = new WebSocket(url);
  } catch (err) {
    S.ws.state = 'error';
    scheduleRetry();
    return;
  }

  ws.onopen = () => {
    S.ws.state = 'open';
    S.ws.tries = 0;
    S.ws.since = Date.now();
    markDirty('pills');
    // api-service's stream is push-only; the server-side receive() is what
    // detects a dropped client, so send one byte to keep that read alive.
    try { ws.send('hello'); } catch { /* ignore */ }
  };

  ws.onmessage = (msg) => {
    S.ws.events += 1;
    S.ws.lastAt = Date.now();
    let env;
    try { env = JSON.parse(msg.data); } catch { return; }
    absorb(env);
  };

  ws.onerror = () => { S.ws.state = 'error'; markDirty('pills'); };

  ws.onclose = () => {
    ws = null;
    if (closedByUs) { S.ws.state = 'idle'; markDirty('pills'); return; }
    S.ws.state = 'closed';
    markDirty('pills');
    scheduleRetry();
  };
}

export function disconnect() {
  closedByUs = true;
  clearTimeout(retryTimer);
  if (ws) { try { ws.close(); } catch { /* ignore */ } }
}

function scheduleRetry() {
  S.ws.tries += 1;
  const wait = Math.min(8000, 700 * S.ws.tries);
  retryTimer = setTimeout(connect, wait);
}

/* ── the reducer ──────────────────────────────────────────────── */
function absorb(env) {
  const type = env.event_type || 'unknown';
  const p = env.payload || {};
  S.typeCounts[type] = (S.typeCounts[type] || 0) + 1;
  const at = Date.now();

  switch (type) {
    case 'VehiclePositionUpdated':
      S.vehicles.set(p.vehicle_id, {
        lat: p.lat, lon: p.lon, type: p.vehicle_type || '',
        speed: p.speed_mps, heading: p.heading_deg, edge: p.edge_id, at,
      });
      markDirty('map');
      break;

    case 'ApproachState':
      S.approach.set(p.movement_id, {
        q_pcu: p.q_pcu, occupancy: p.occupancy, arrival: p.arrival_rate_pcu_s, at,
      });
      markDirty('traffic', 'map');
      break;

    case 'SignalChanged': {
      const id = p.intersection_id;
      const prev = S.signals.get(id) || { changes: 0, sources: {} };
      prev.phase = p.phase_id;
      prev.source = p.source;
      prev.at = at;
      prev.changes = (prev.changes || 0) + 1;
      prev.sources[p.source] = (prev.sources[p.source] || 0) + 1;
      prev.faulted = false;
      S.signals.set(id, prev);
      S.sourceCounts[p.source] = (S.sourceCounts[p.source] || 0) + 1;
      markDirty('signals', 'map');
      break;
    }

    case 'SignalFaulted': {
      const id = p.intersection_id;
      const prev = S.signals.get(id) || { changes: 0, sources: {} };
      prev.faulted = p.fault_type;
      prev.faultDetail = p.detail;
      prev.at = at;
      S.signals.set(id, prev);
      S.faults.unshift({ at, id, type: p.fault_type, detail: p.detail });
      S.faults.length = Math.min(S.faults.length, 120);
      markDirty('signals', 'map');
      break;
    }

    case 'AnomalyUpdated':
      S.anomalies.set(p.anomaly_id, { ...p, at });
      markDirty('anomalies', 'map', 'traffic');
      break;

    case 'EmergencyRequestUpdated': {
      const prev = S.requests.get(p.request_id);
      S.requests.set(p.request_id, { ...p, at, history: [...(prev?.history || []), {
        at, state: p.state, detail: p.detail, actor: p.actor,
      }].slice(-40) });
      if (p.detail && /reroute|rerouted|blocked ahead|cheaper/i.test(p.detail)) {
        S.rerouteLog.unshift({ at, request: p.request_id, detail: p.detail, state: p.state });
        S.rerouteLog.length = Math.min(S.rerouteLog.length, 40);
      }
      markDirty('emergency', 'map');
      break;
    }

    case 'EmergencyVehicleUpdated':
      S.evs.set(p.vehicle_id, { ...p, at });
      markDirty('emergency', 'map');
      break;

    case 'GreenCorridorUpdated':
      // green_corridor_updated.avsc: each event is a full current snapshot
      // (status, reservations, peak_concurrency) -- not a per-junction
      // granted/released delta -- so a plain overwrite per corridor_id is
      // correct and keeps the latest reservation list intact.
      S.corridors.set(p.corridor_id, { ...p, at });
      markDirty('emergency', 'signals', 'map');
      break;

    case 'IncidentCandidate':
    case 'IncidentDetected':
    case 'IncidentUpdated':
      markDirty('incidents');
      window.dispatchEvent(new CustomEvent('itms-incident'));
      break;

    default:
      break;
  }

  // Everything except the two firehose topics goes in the readable ring.
  if (type !== 'VehiclePositionUpdated' && type !== 'ApproachState') {
    S.events.unshift({
      at, type, source: env.source, key: env.partition_key,
      cat: CATEGORY[type] ?? '', line: summarise(type, p),
      payload: p,
    });
    S.events.length = Math.min(S.events.length, RING);
    markDirty('log');
  } else if (S.ws.events % 50 === 0) {
    markDirty('log'); // keep the type counters moving without per-event work
  }
}

/* One readable line per event. Deliberately field-level rather than a JSON
   dump: the point of the log is to be skimmable while something is going
   wrong. The full payload is one click away. */
function summarise(type, p) {
  switch (type) {
    case 'SignalChanged': return `${p.intersection_id} → phase ${p.phase_id}   [${p.source}]`;
    case 'SignalFaulted': return `${p.intersection_id}   ${p.fault_type}: ${p.detail || ''}`;
    case 'AnomalyUpdated':
      return `${p.status} ${p.anomaly_type}/${p.severity} on ${p.edge_id}` +
        (p.vehicle_id ? `   veh ${p.vehicle_id}` : '') + (p.detail ? `   — ${p.detail}` : '');
    case 'EmergencyRequestUpdated':
      return `${p.request_id?.slice(0, 8)} ${p.state}` +
        (p.destination_edge ? `   → ${p.destination_edge}` : '') +
        (p.eta_s != null ? `   eta ~${Math.round(p.eta_s)}s` : '') +
        (p.actor ? `   [${p.actor}]` : '') +
        (p.detail ? `   — ${p.detail}` : '');
    case 'EmergencyVehicleUpdated':
      return `${p.vehicle_id}   ${(p.status || '').toLowerCase()}   ${Number(p.speed_mps || 0).toFixed(1)} m/s` +
        `   ${Math.round((p.route_progress || 0) * 100)}% of route`;
    case 'GreenCorridorUpdated':
      return `${p.event} corridor ${p.corridor_id?.slice(0, 8) ?? p.corridor_id}   status ${p.status}` +
        `   ${(p.reservations || []).length} junction(s) reserved`;
    case 'IncidentCandidate':
      return `${p.intersection_id}/${p.link_id}   p=${Number(p.fused_probability).toFixed(3)}` +
        ` tau=${Number(p.threshold_tau).toFixed(3)}   ${p.detector_version || ''}`;
    case 'IncidentDetected':
    case 'IncidentUpdated':
      return `${p.incident_id?.slice(0, 8)} ${p.state || p.status || ''}   ${p.detail || ''}`;
    case 'SystemHeartbeat': return `${p.service} seq ${p.seq}`;
    default: return JSON.stringify(p).slice(0, 160);
  }
}

/* Vehicles never announce that they left, so they are pruned by silence. */
export function pruneVehicles() {
  const cutoff = Date.now() - VEHICLE_TTL_MS;
  let removed = 0;
  for (const [id, v] of S.vehicles) {
    if (v.at < cutoff) { S.vehicles.delete(id); removed += 1; }
  }
  if (removed) markDirty('map');
}

export function resetStream() {
  S.events.length = 0;
  S.typeCounts = {};
  S.vehicles.clear();
  S.approach.clear();
  S.signals.clear();
  S.sourceCounts = {};
  S.faults.length = 0;
  S.anomalies.clear();
  S.requests.clear();
  S.evs.clear();
  S.corridors.clear();
  S.rerouteLog.length = 0;
  S.ws.events = 0;
  markDirty('map', 'signals', 'traffic', 'log', 'anomalies', 'emergency');
}

/* Used by the demo runner to wait for something real to happen rather than
   sleeping a guessed number of seconds. */
export function condition(what) {
  switch (what) {
    case 'vehicles_moving':
      return S.vehicles.size > 0 && [...S.vehicles.values()].some((v) => v.speed > 0.5);
    case 'signal_changed':
      return (S.typeCounts.SignalChanged || 0) > 0;
    case 'anomaly_active':
      return [...S.anomalies.values()].some(isAnomalyActive);
    case 'route_ready':
      // CREATED -> ROUTING -> ROUTE_READY is a real, distinct phase
      // (emergency_request_updated.avsc's EmergencyRequestLifecycle) -- a
      // request only reaches ROUTE_READY once RoutePlanner has produced a
      // route (or CANCELLED if no path exists at all).
      return [...S.requests.values()].some((r) => r.state === 'ROUTE_READY');
    case 'corridor_active':
      return [...S.corridors.values()].some((c) => c.status === 'ACTIVE');
    case 'reroute':
      return S.rerouteLog.length > 0;
    case 'request_completed':
      return [...S.requests.values()].some((r) => r.state === 'COMPLETED');
    case 'run_finished':
      return ['finished', 'stopped', 'failed'].includes(S.run?.state) || !S.status?.stack?.sim?.running;
    default:
      return false;
  }
}

export function conditionLabel(what) {
  return {
    vehicles_moving: 'vehicles moving in the corridor',
    signal_changed: 'a commanded phase change',
    anomaly_active: 'an anomaly reported ACTIVE',
    route_ready: 'a calculated route',
    corridor_active: 'the green corridor to arm',
    reroute: 'an automatic re-route',
    request_completed: 'the request to complete',
    run_finished: 'the run to finish',
  }[what] || what;
}
