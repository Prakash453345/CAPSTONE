/* Everything the user can do: start and stop runs, publish operator commands,
   decide incidents, run gate scripts, and drive the guided demos.

   Every command here is built to the Avro schema in `contracts/events/` and
   posted through `api-service`'s `POST /v1/commands`, which is the only way
   into the simulation. The site has no private channel -- if a command works
   here it works from `curl`, and if it fails the schema rejected it. */

import { S, api, toast, markDirty } from './state.js';
import { condition, conditionLabel, resetStream } from './stream.js';
import * as V from './views.js';

const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
  : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  }));
const nowMs = () => Date.now();
const val = (id) => document.getElementById(id)?.value ?? '';
const intOrNull = (id) => { const v = val(id).trim(); return v === '' ? null : Number(v); };

/* ── stack ────────────────────────────────────────────────────── */
export async function stackAction(action, what) {
  const res = await api(`/api/stack/${action}`, { what });
  const detail = res.detail || {};
  for (const [k, v] of Object.entries(detail)) {
    if (v && v.ok === false) toast(`${k}: could not ${action}`, v.reason || '', 'bad', 9000);
  }
  if (res.ok !== false && !Object.values(detail).some((v) => v && v.ok === false)) {
    toast(action === 'start' ? 'Started' : 'Stopped', what === 'all' ? 'bus + api-service' : what, 'ok', 3000);
  }
  refreshStatus();
}

/* ── runs ─────────────────────────────────────────────────────── */
export function collectRunConfig() {
  const cfg = {
    demand: S.form.demand,
    controller: S.form.controller,
    engine: S.form.engine,
    realtime_factor: Number(val('rt-factor')),
    step_length: 1.0,
    max_steps: intOrNull('max-steps') || 0,
    seed: intOrNull('seed'),
    warmup_s: Number(val('warmup') || 600),
    label: val('run-label').trim(),
  };
  if (S.form.demand === 'custom') {
    cfg.od = {
      origin: val('od-origin'),
      destination: val('od-dest'),
      count: Number(val('od-count') || 40),
      target_arrivals: Number(val('od-target') || val('od-count') || 40),
      depart_window_s: Number(val('od-window') || 240),
      background: val('od-background'),
    };
  }
  if (S.form.weightsEnabled && S.boot?.route_cost_weights) {
    const weights = {};
    for (const f of S.boot.route_cost_weights) {
      const v = val(`w-${f.id}`);
      if (v !== '') weights[f.id] = Number(v);
    }
    cfg.weights = weights;
  }
  return cfg;
}

export async function startRun(overrideConfig) {
  const cfg = overrideConfig || collectRunConfig();
  const hint = document.getElementById('start-hint');
  if (hint) { hint.className = 'hint'; hint.textContent = 'starting…'; }
  resetStream();
  const res = await api('/api/run/start', cfg);
  if (!res.ok) {
    if (hint) { hint.className = 'hint bad'; hint.textContent = res.reason || 'could not start'; }
    toast('Run did not start', res.reason || '', 'bad', 10000);
    return null;
  }
  if (hint) { hint.className = 'hint ok'; hint.textContent = `started — run ${res.run.id}`; }
  toast('Run started', res.run.label || res.run.id, 'ok', 3500);
  await refreshStatus();
  await refreshRuns();
  return res.run;
}

export async function stopRun() {
  const res = await api('/api/run/stop', {});
  toast(res.ok ? 'Run stopped' : 'Could not stop', res.reason || '', res.ok ? '' : 'bad');
  await refreshStatus();
  await refreshRuns();
}

export async function refreshStatus() {
  const res = await api('/api/status');
  if (res && res.stack) {
    S.status = res;
    S.run = res.run || null;
    markDirty('pills', 'control', 'map', 'signals', 'gates');
  }
  return res;
}

export async function refreshRuns() {
  const res = await api('/api/runs');
  if (res.ok) { S.runs = res.runs || []; markDirty('kpis'); }
}

export async function compareSelected() {
  const ids = [...S.selected];
  if (ids.length < 2) return;
  const res = await api('/api/runs/compare', { ids });
  V.renderCompare(res.ok ? res : null);
  if (!res.ok) toast('Could not compare', res.reason || '', 'bad');
}

/* ── operator commands ────────────────────────────────────────── */
async function command(eventType, payload, label) {
  const res = await api('/api/commands', { event_type: eventType, payload });
  if (!res.ok) {
    toast(`${label} rejected`, res.reason || res.detail || '', 'bad', 11000);
    return null;
  }
  return res.result;
}

export async function createAnomaly(override) {
  const hint = document.getElementById('an-hint');
  const payload = override || {
    edge_id: val('an-edge'),
    anomaly_type: val('an-type'),
    severity: val('an-sev'),
    duration_s: intOrNull('an-dur'),
  };
  if (!payload.edge_id) {
    if (hint) { hint.className = 'hint bad'; hint.textContent = 'pick a road first'; }
    return null;
  }
  const id = uuid();
  // Real fields, per contracts/events/anomaly_create_requested.avsc: all 5
  // anomaly_type values and all 4 severities are genuine (see the severity
  // note above the form for what each one actually does to the simulation),
  // duration_s is a real optional auto-clear timer, and requested_at is
  // required -- there is no server-side default for it.
  const full = {
    anomaly_id: id,
    edge_id: payload.edge_id,
    anomaly_type: payload.anomaly_type || 'LANE_BLOCKAGE',
    severity: payload.severity || 'HIGH',
    duration_s: payload.duration_s != null ? Number(payload.duration_s) : null,
    operator: 'operator:testlab',
    requested_at: nowMs(),
  };
  const res = await command('AnomalyCreateRequested', full, 'Anomaly');
  if (res && hint) {
    hint.className = 'hint ok';
    hint.textContent = S.status?.stack?.sim?.running
      ? 'published — the simulation applies it on its next tick'
      : 'published, but nothing is running to drain it';
  }
  if (res && !S.status?.stack?.sim?.running) {
    toast('Nothing is running', 'The command is on the bus, but no simulation is draining it. Start a run first.', 'warn', 9000);
  }
  return res ? id : null;
}

export async function clearAnomaly(anomalyId, resolution) {
  // AnomalyClearRequested (anomaly_clear_requested.avsc): `resolution` is a
  // real enum -- RESOLVED (the disruption is genuinely over) vs CANCELLED
  // (created by mistake, nothing about the road changed).
  return command('AnomalyClearRequested', {
    anomaly_id: anomalyId,
    resolution: resolution || 'RESOLVED',
    operator: 'operator:testlab',
    requested_at: nowMs(),
  }, 'Anomaly clear');
}

export async function dispatch(override) {
  const hint = document.getElementById('ev-hint');
  const payload = override || {
    vehicle_kind: val('ev-kind') || 'AMBULANCE',
    source_edge: val('ev-src'),
    destination_edge: val('ev-dst'),
  };
  if (!payload.source_edge || !payload.destination_edge) {
    if (hint) { hint.className = 'hint bad'; hint.textContent = 'pick a source and a destination road first'; }
    return null;
  }
  const requestId = uuid();
  // Real fields, per contracts/events/emergency_request_created.avsc: the
  // operator names both the start AND the destination edge directly -- the
  // router (RoutePlanner, six-term cost model) plans between exactly those
  // two, it does not pick a facility on its own. vehicle_id is this unit's
  // own id, distinct from request_id.
  const res = await command('EmergencyRequestCreated', {
    request_id: requestId,
    vehicle_id: `ev-${requestId.slice(0, 8)}`,
    vehicle_kind: payload.vehicle_kind || 'AMBULANCE',
    source_edge: payload.source_edge,
    destination_edge: payload.destination_edge,
    priority: 1,
    operator: 'operator:testlab',
    requested_at: nowMs(),
  }, 'Dispatch');
  if (res && hint) {
    hint.className = 'hint ok';
    hint.textContent = S.status?.stack?.sim?.running
      ? 'dispatched — routing against live traffic + active anomalies'
      : 'published, but nothing is running to route it';
  }
  return res ? requestId : null;
}

export async function emergencyCommand(requestId, action, reason) {
  // EmergencyCommand (emergency_command.avsc): all three actions are real --
  // CANCEL, RECALCULATE, ACTIVATE_CORRIDOR -- and the field is `action`,
  // upper-case, matched exactly by EmergencyController.handle_command.
  return command('EmergencyCommand', {
    request_id: requestId,
    action,
    reason: reason || '',
    operator: 'operator:testlab',
    requested_at: nowMs(),
  }, action);
}

/* ── incidents ────────────────────────────────────────────────── */
export async function refreshIncidents() {
  const res = await api('/api/incidents');
  const hint = document.getElementById('incident-hint');
  if (res.ok) {
    S.incidents = res.incidents || [];
    if (hint) { hint.className = 'hint'; hint.textContent = `${S.incidents.length} in the registry`; }
  } else if (hint) {
    hint.className = 'hint bad';
    hint.textContent = res.reason || 'could not read the registry';
  }
  markDirty('incidents');
}

export async function incidentDecision(incidentId, action) {
  const classification = document.getElementById(`cls-${incidentId}`)?.value || 'unknown';
  const res = await api(`/api/incidents/${encodeURIComponent(incidentId)}/${action}`, {
    actor: 'operator:testlab',
    classification,
    detail: `${action} from the ITMS test lab`,
  });
  if (!res.ok) toast(`Could not ${action}`, res.reason || '', 'bad', 11000);
  else toast(action === 'confirm' ? 'Incident confirmed' : 'Candidate rejected', incidentId.slice(0, 8), 'ok');
  refreshIncidents();
}

/* ── gates ────────────────────────────────────────────────────── */
export async function runGate(gateId) {
  const res = await api(`/api/gates/${encodeURIComponent(gateId)}/start`, {});
  if (!res.ok) toast('Gate did not start', res.reason || '', 'bad', 10000);
  else toast('Gate running', 'Output appears below. This can take minutes.', 'ok', 6000);
  refreshStatus();
}

export async function stopGate() {
  await api('/api/gates/stop', {});
  refreshStatus();
}

export async function loadResults() {
  const res = await api('/api/results');
  V.renderResults(res);
}

export async function viewResult(name) {
  const res = await api(`/api/result?name=${encodeURIComponent(name)}`);
  V.renderResultView(res);
}

/* ── scenario validation ──────────────────────────────────────── */
let validateTimer = null;
export function scheduleValidate() {
  clearTimeout(validateTimer);
  validateTimer = setTimeout(validateOd, 220);
}

export async function validateOd() {
  if (S.form.demand !== 'custom') return;
  const body = {
    origin: val('od-origin'),
    destination: val('od-dest'),
    count: Number(val('od-count') || 40),
    target_arrivals: Number(val('od-target') || 0),
    depart_window_s: Number(val('od-window') || 240),
    background: val('od-background'),
  };
  if (!body.origin || !body.destination) { V.renderOdCheck(null); return; }
  const res = await api('/api/scenario/validate', body);
  V.renderOdCheck(res);
}

/* ── guided demos ─────────────────────────────────────────────── */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runDemo(demoId, goto) {
  if (S.demo) return;
  const def = S.boot.demos.find((d) => d.id === demoId);
  if (!def) return;
  S.demo = { def, i: 0, states: [], notes: [], abort: false };
  markDirty('demos');
  V.renderDemos();
  V.renderDemoRunner();

  for (let i = 0; i < def.steps.length; i += 1) {
    if (S.demo?.abort) break;
    S.demo.i = i;
    S.demo.states[i] = 'now';
    V.renderDemoRunner();
    let ok = true;
    let note = '';
    try {
      note = await runStep(def.steps[i], goto);
    } catch (err) {
      ok = false;
      note = err.message || String(err);
    }
    if (S.demo?.abort) break;
    S.demo.states[i] = ok ? 'done' : (def.steps[i].optional ? 'done' : 'fail');
    S.demo.notes[i] = note;
    V.renderDemoRunner();
    if (!ok && !def.steps[i].optional) {
      toast('Demo stopped', note, 'bad', 12000);
      break;
    }
  }
  if (S.demo && !S.demo.abort) toast('Demo finished', def.title, 'ok', 6000);
  S.demo = null;
  V.renderDemos();
  V.renderDemoRunner();
}

export function abortDemo() {
  if (S.demo) { S.demo.abort = true; toast('Demo aborted', 'Anything already started keeps running.', 'warn'); }
}

async function runStep(st, goto) {
  switch (st.kind) {
    case 'note':
      await sleep((st.wait_s || 2) * 1000);
      return '';

    case 'goto':
      goto(st.section);
      await sleep(500);
      return '';

    case 'ensure_stack': {
      await stackAction('start', 'all');
      for (let i = 0; i < 30; i += 1) {
        await refreshStatus();
        if (S.status?.stack?.redis?.ok && S.status?.stack?.api?.ok) return 'bus + api up';
        await sleep(700);
      }
      throw new Error('the bus or api-service never came up — see the Control room banner');
    }

    case 'start_run': {
      if (S.status?.stack?.sim?.running) {
        await stopRun();
        await sleep(1500);
      }
      const run = await startRun({ ...st.config, label: st.label });
      if (!run) throw new Error('the run would not start');
      await sleep(1200);
      return `run ${run.id}`;
    }

    case 'wait_until': {
      const timeout = (st.timeout_s || 60) * 1000;
      const t0 = Date.now();
      while (Date.now() - t0 < timeout) {
        if (S.demo?.abort) return 'aborted';
        if (condition(st.what)) return `saw ${conditionLabel(st.what)} after ${Math.round((Date.now() - t0) / 1000)}s`;
        await sleep(600);
      }
      if (st.optional) return `did not see ${conditionLabel(st.what)} within ${st.timeout_s}s — treated as acceptable`;
      throw new Error(`never saw ${conditionLabel(st.what)} within ${st.timeout_s}s`);
    }

    case 'anomaly': {
      const id = await createAnomaly(st.payload);
      if (!id) throw new Error('the anomaly command was rejected');
      return `anomaly ${id.slice(0, 8)} on ${st.payload.edge_id}`;
    }

    case 'dispatch': {
      const id = await dispatch(st.payload);
      if (!id) throw new Error('the dispatch command was rejected');
      return `request ${id.slice(0, 8)}`;
    }

    case 'corridor': {
      // ACTIVATE_CORRIDOR is a real, explicit command -- it must be sent;
      // corridor activation is never automatic. It also only takes effect
      // (and spawns the vehicle in SUMO) while the request is still
      // ROUTE_READY, so this picks the most recently updated one in that
      // state rather than any older ROUTE_READY request.
      const ready = [...S.requests.values()]
        .filter((r) => r.state === 'ROUTE_READY' && r.route)
        .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))[0];
      if (!ready) throw new Error('no ROUTE_READY request to activate a corridor for');
      const res = await emergencyCommand(ready.request_id, 'ACTIVATE_CORRIDOR');
      if (!res) throw new Error('ACTIVATE_CORRIDOR was rejected');
      return `corridor activation requested for ${ready.request_id.slice(0, 8)}`;
    }

    case 'compare_last': {
      await refreshRuns();
      const ids = S.runs.slice(0, st.n || 2).map((r) => r.id);
      S.selected = new Set(ids);
      markDirty('kpis');
      goto('kpis');
      await compareSelected();
      return `compared ${ids.length} runs`;
    }

    default:
      return `unknown step ${st.kind}`;
  }
}
