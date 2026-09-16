/* Shared state, the API client, and small formatting helpers.
   One mutable object rather than a framework: the whole app is a few screens
   over one stream, and a store plus render-on-tick is the least machinery that
   does that honestly. */

export const S = {
  boot: null,            // /api/bootstrap, once
  status: null,          // /api/status, 1 Hz
  run: null,             // the runner's own status.json, via /api/status
  runs: [],              // run history
  selected: new Set(),   // run ids ticked for comparison

  ws: { state: 'idle', url: null, tries: 0, events: 0, lastAt: 0, since: 0 },

  events: [],            // ring of decoded envelopes (vehicle positions excluded)
  typeCounts: {},        // event_type -> count
  vehicles: new Map(),   // vehicle_id -> {lat, lon, type, speed, heading, edge, at}
  approach: new Map(),   // edge_id -> {q_pcu, occupancy, arrival, at}
  signals: new Map(),    // tls_id -> {phase, source, at, changes, sources:{}}
  sourceCounts: {},      // arbitration source -> count
  faults: [],            // SignalFaulted, newest first
  anomalies: new Map(),  // anomaly_id -> payload
  requests: new Map(),   // request_id -> payload
  evs: new Map(),        // vehicle_id -> payload
  corridors: new Map(),  // corridor_id -> payload
  incidents: [],         // /api/incidents
  rerouteLog: [],        // request detail lines mentioning a reroute

  view: 'control',
  pick: null,            // {target, label} while picking an edge on the map
  form: {
    demand: 'light',
    controller: 'acamp',
    engine: 'testlab',
    weightsEnabled: false,
    weights: {},          // route-cost weight id -> number the user typed
  },
  // Street tiles on by default: the road lines alone (no basemap) read as an
  // abstract diagram with nothing to orient against, which is confusing on
  // first look. The dim CartoDB layer underneath gives real streets for
  // context; the "Street tiles" button still lets you switch it back off.
  layers: { roads: true, vehicles: true, signals: true, anomalies: true, emergency: true, tiles: true, labels: false },
  logFilter: { hidden: new Set(['VehiclePositionUpdated', 'ApproachState']), q: '' },
  demo: null,            // {def, i, states:[], abort}
  verdicts: {},          // milestone id -> 'pass'|'fail'|'skip'
  dirty: new Set(),      // view names needing a re-render
};

/* ── verdicts persist locally; they are the user's own observations ── */
const VKEY = 'itms-testlab-verdicts';
try { S.verdicts = JSON.parse(localStorage.getItem(VKEY) || '{}'); } catch { S.verdicts = {}; }
export function saveVerdicts() {
  try { localStorage.setItem(VKEY, JSON.stringify(S.verdicts)); } catch { /* private window */ }
}

/* ── api ───────────────────────────────────────────────────────── */
export async function api(path, body, method) {
  const opts = { method: method || (body ? 'POST' : 'GET'), headers: {} };
  if (body !== undefined && body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(path, opts);
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { ok: false, reason: text.slice(0, 300) }; }
    if (!res.ok && data.ok === undefined) data.ok = false;
    return data;
  } catch (err) {
    return { ok: false, reason: `the control server is not answering (${err.message}). Is server.py still running?` };
  }
}

/* ── toasts ────────────────────────────────────────────────────── */
export function toast(title, msg, kind = '', ms = 5200) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = `<b></b><span></span>`;
  el.querySelector('b').textContent = title;
  el.querySelector('span').textContent = msg || '';
  host.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 320);
  }, ms);
}

/* ── formatting ────────────────────────────────────────────────── */
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function num(v, digits = 0) {
  if (v === null || v === undefined || v === '' || Number.isNaN(v)) return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function dur(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

export const clock = (ms) => new Date(ms).toLocaleTimeString(undefined, { hour12: false });

export function ago(ts) {
  if (!ts) return '—';
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

/* Short label for an edge: its street name when the OSM data has one, which
   is far easier to pick out of a dropdown than a raw way id. */
export function edgeLabel(id) {
  const e = S.boot?.network?.edges?.[id];
  if (!e) return id;
  const bits = [];
  if (e.name) bits.push(e.name);
  bits.push(`${Math.round(e.length_m)} m`);
  if (e.num_lanes > 1) bits.push(`${e.num_lanes} lanes`);
  if (e.signalised_entry_tls?.length) bits.push('signalised');
  return `${id} — ${bits.join(' · ')}`;
}

export function markDirty(...views) {
  views.forEach((v) => S.dirty.add(v));
}

/* ── real event vocabulary ────────────────────────────────────────
   This was drafted once against a much simpler, and once against a
   simplified-but-wrong, guess at the backend's state machine. The actual
   source of truth is the Avro schemas in contracts/events/ (read directly
   off the real `komal` branch, not re-derived from behaviour):

     anomaly_updated.avsc         status: ACTIVE | RESOLVED | CANCELLED  (upper-case)
     emergency_request_updated.avsc  state: CREATED | ROUTING | ROUTE_READY |
                                            GREEN_CORRIDOR_ACTIVE | IN_TRANSIT |
                                            COMPLETED | CANCELLED  (upper-case)
     emergency_vehicle_updated.avsc  status: IDLE | ASSIGNED | EN_ROUTE | ARRIVED (upper-case)
     green_corridor_updated.avsc     event: proposed|activated|junction_passed|terminated (lower-case)
                                      status: PROPOSED|ACTIVE|RESTORING|COMPLETED|CANCELLED (upper-case)

   Centralised here so every screen and the stream reducer agree on the
   same names instead of each guessing its own casing. */
export const EMERGENCY_OPEN_STATES = new Set([
  'CREATED', 'ROUTING', 'ROUTE_READY', 'GREEN_CORRIDOR_ACTIVE', 'IN_TRANSIT',
]);
export const EMERGENCY_TERMINAL_STATES = new Set(['COMPLETED', 'CANCELLED']);
export const isEmergencyOpen = (r) => EMERGENCY_OPEN_STATES.has(r?.state);
export const isAnomalyActive = (a) => a?.status === 'ACTIVE';
export const isCorridorActive = (c) => c?.status === 'ACTIVE';
