/* Entry point: boot, route, poll, and wire every control on the page.

   The render loop is a dirty-flag check on requestAnimationFrame: the stream
   marks what changed, this decides what to redraw, and only the visible screen
   is touched. That is what keeps a heavy-demand run (hundreds of events a
   second) from turning into a laggy page. */

import { S, api, toast, saveVerdicts, markDirty, esc } from './state.js';
import { connect, pruneVehicles } from './stream.js';
import * as V from './views.js';
import * as A from './actions.js';
import { initMap, drawMap, invalidateMapSize, flyToEdge, mapReady } from './map.js';

const VIEWS = ['control', 'map', 'signals', 'traffic', 'log', 'anomalies',
  'emergency', 'incidents', 'kpis', 'milestones', 'demos', 'gates', 'settings'];

/* ── routing ──────────────────────────────────────────────────── */
function goto(view) {
  if (!VIEWS.includes(view)) view = 'control';
  S.view = view;
  document.querySelectorAll('.view').forEach((el) => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  document.querySelectorAll('#sidenav button[data-go]').forEach((b) => {
    b.classList.toggle('active', b.dataset.go === view);
  });
  if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  if (view === 'map') { initMap(); invalidateMapSize(); drawMap(true); }
  if (view === 'incidents') A.refreshIncidents();
  if (view === 'gates') A.loadResults();
  if (view === 'kpis') A.refreshRuns();
  renderView(view, true);
  document.getElementById('main')?.scrollTo({ top: 0 });
}

/* ── render dispatch ──────────────────────────────────────────── */
function renderView(view, force = false) {
  switch (view) {
    case 'control':
      V.renderSetupBanner(); V.renderStack(); V.renderDemandSeg();
      V.renderOptionRows(); V.renderWeights(); V.renderRunLive();
      break;
    case 'map': if (mapReady()) { drawMap(force); V.renderMapRail(); } break;
    case 'signals': V.renderSignals(); break;
    case 'traffic': V.renderTraffic(); break;
    case 'log': V.renderLog(); break;
    case 'anomalies': V.renderAnomalies(); break;
    case 'emergency': V.renderEmergency(); break;
    case 'incidents': V.renderIncidents(); break;
    case 'kpis': V.renderKpis(); break;
    case 'milestones': V.renderMilestones(); break;
    case 'demos': V.renderDemos(); V.renderDemoRunner(); break;
    case 'gates': V.renderGates(); break;
    case 'settings': V.renderSettings(); break;
    default: break;
  }
}

function frame() {
  if (S.dirty.size) {
    const d = S.dirty;
    S.dirty = new Set();
    if (d.has('pills')) { V.renderPills(); V.renderRunClock(); V.renderNavBadges(); }
    if (d.has('pick')) V.renderPickBanner();
    if (d.has(S.view) || d.has('all')) renderView(S.view);
    else if (S.view === 'map' && (d.has('map') || d.has('traffic'))) {
      drawMap(); V.renderMapRail();
    }
  }
  requestAnimationFrame(frame);
}

/* ── polling ──────────────────────────────────────────────────── */
async function pollStatus() {
  await A.refreshStatus();
  V.renderPills(); V.renderRunClock(); V.renderNavBadges();
  if (S.view === 'control') { V.renderStack(); V.renderRunLive(); }
  if (S.view === 'map') { drawMap(true); V.renderMapRail(); }
  if (S.view === 'gates') V.renderGates();
  if (S.view === 'traffic') V.renderTraffic();
  if (S.view === 'signals') V.renderSignals();
}

const logSeq = { sim: 0, api: 0, redis: 0, gate: 0 };
async function pollLogs() {
  const targets = S.view === 'control' ? ['sim']
    : S.view === 'gates' ? ['gate']
      : S.view === 'settings' ? ['api', 'redis'] : [];
  for (const name of targets) {
    const el = document.querySelector(`[data-log="${name}"]`);
    if (!el) continue;
    const res = await api(`/api/logs?name=${name}&since=${logSeq[name]}`);
    if (!res.ok || !res.lines) continue;
    if (res.seq < logSeq[name]) { logSeq[name] = 0; el.textContent = ''; }
    if (!res.lines.length) continue;
    logSeq[name] = res.seq;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    const html = res.lines.map((l) => {
      const cls = /error|traceback|exception|failed|refused/i.test(l.s) ? 'err'
        : /warn|missing|inactive|not set/i.test(l.s) ? 'warnl'
          : l.s.startsWith('$ ') ? 'cmd' : '';
      return cls ? `<span class="${cls}">${esc(l.s)}</span>` : esc(l.s);
    }).join('\n');
    if (el.dataset.seeded !== '1') { el.innerHTML = html; el.dataset.seeded = '1'; }
    else el.innerHTML += '\n' + html;
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
}

/* ── wiring ───────────────────────────────────────────────────── */
function wire() {
  document.getElementById('sidenav').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-go]');
    if (btn) goto(btn.dataset.go);
  });

  window.addEventListener('hashchange', () => goto(location.hash.slice(1)));

  // help sheet
  const help = document.getElementById('help');
  document.getElementById('btn-help').onclick = () => { help.hidden = false; };
  document.getElementById('help-close').onclick = () => { help.hidden = true; };
  help.addEventListener('click', (e) => { if (e.target === help) help.hidden = true; });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!help.hidden) help.hidden = true;
      else if (S.pick) { S.pick = null; markDirty('pick'); }
    }
  });

  document.getElementById('btn-stop-run').onclick = A.stopRun;
  document.getElementById('btn-stop-run2').onclick = A.stopRun;
  document.getElementById('btn-start-run').onclick = () => A.startRun();

  // one delegated click handler for everything data-attribute driven
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-stack],[data-demand],[data-controller],[data-engine],'
      + '[data-pick],[data-clear-anomaly],[data-corridor],[data-recalc],[data-cancel-req],'
      + '[data-showroute],[data-incident],[data-gate],[data-gate-stop],[data-result],'
      + '[data-delrun],[data-verdict],[data-go2],[data-demo],[data-flyto],[data-etype]');
    if (!t) return;
    const d = t.dataset;

    if (d.stack) { const [act, what] = d.stack.split(':'); await A.stackAction(act, what); return; }

    if (d.demand) {
      S.form.demand = d.demand;
      V.renderDemandSeg();
      if (d.demand === 'custom') A.validateOd();
      return;
    }
    if (d.controller) { S.form.controller = d.controller; V.renderOptionRows(); return; }
    if (d.engine) {
      S.form.engine = d.engine;
      V.renderOptionRows();
      if (d.engine !== 'testlab') {
        toast('Repo entrypoint selected', 'No KPI scoring and no live counters — that path does not write a status file. The map and event log still work.', 'warn', 9000);
      }
      return;
    }

    if (d.pick) {
      const map = { origin: ['od-origin', 'origin road'], destination: ['od-dest', 'destination road'],
        anomaly: ['an-edge', 'anomaly road'], evsource: ['ev-src', 'unit start road'],
        evdest: ['ev-dst', 'unit destination road'] }[d.pick];
      if (!map) return;
      S.pick = { target: map[0], label: map[1] };
      markDirty('pick');
      document.querySelectorAll('[data-pick]').forEach((b) => b.classList.toggle('picking', b.dataset.pick === d.pick));
      goto('map');
      toast('Pick a road', `Click the road on the map to set the ${map[1]}.`, '', 6000);
      return;
    }

    // AnomalyClearRequested's `resolution` is a real enum (RESOLVED vs
    // CANCELLED, i.e. "genuinely over" vs "created by mistake") -- the
    // Anomalies panel now has two buttons, each carrying its own
    // data-resolution.
    if (d.clearAnomaly) { await A.clearAnomaly(d.clearAnomaly, d.resolution || 'RESOLVED'); return; }
    // All three EmergencyCommand actions are real (emergency_command.avsc's
    // EmergencyCommandAction enum) and upper-case on the wire --
    // EmergencyController.handle_command matches the string exactly.
    if (d.corridor) { await A.emergencyCommand(d.corridor, 'ACTIVATE_CORRIDOR'); return; }
    if (d.recalc) { await A.emergencyCommand(d.recalc, 'RECALCULATE'); return; }
    if (d.cancelReq) { await A.emergencyCommand(d.cancelReq, 'CANCEL'); return; }
    if (d.showroute) { S.showRoute = d.showroute; V.renderEmergency(); return; }
    if (d.incident) { await A.incidentDecision(d.incident, d.action); return; }
    if (d.gate) { await A.runGate(d.gate); return; }
    if (d.gateStop) { await A.stopGate(); return; }
    if (d.result) { await A.viewResult(d.result); return; }
    if (d.delrun) {
      await api(`/api/runs/${encodeURIComponent(d.delrun)}`, null, 'DELETE');
      S.selected.delete(d.delrun);
      await A.refreshRuns();
      V.renderKpis();
      return;
    }
    if (d.verdict) {
      const [id, verdict] = d.verdict.split(':');
      S.verdicts[id] = S.verdicts[id] === verdict ? undefined : verdict;
      if (!S.verdicts[id]) delete S.verdicts[id];
      saveVerdicts();
      V.renderMilestones();
      return;
    }
    if (d.go2) { goto(d.go2); return; }
    if (d.demo) { A.runDemo(d.demo, goto); return; }
    if (d.flyto) { goto('map'); flyToEdge(d.flyto); return; }

    if (d.etype) {
      if (d.etype === '__all') S.logFilter.hidden.clear();
      else if (d.etype === '__none') Object.keys(S.typeCounts).forEach((k) => S.logFilter.hidden.add(k));
      else if (S.logFilter.hidden.has(d.etype)) S.logFilter.hidden.delete(d.etype);
      else S.logFilter.hidden.add(d.etype);
      V.renderLog();
    }
  });

  // event-log search + traffic sorting + run selection + severity note
  document.addEventListener('input', (e) => {
    if (e.target.id === 'event-q') { S.logFilter.q = e.target.value; V.renderLog(); }
    if (['od-origin', 'od-dest', 'od-count', 'od-target', 'od-window', 'od-background'].includes(e.target.id)) {
      if (e.target.id === 'od-count') {
        const tgt = document.getElementById('od-target');
        if (tgt && !tgt.dataset.touched) tgt.value = e.target.value;
      }
      A.scheduleValidate();
    }
    if (e.target.id === 'od-target') e.target.dataset.touched = '1';
    if (e.target.id === 'an-sev') V.renderSeverityNote();
    if (e.target.id.startsWith('w-')) S.form.weights[e.target.id.slice(2)] = e.target.value;
  });
  document.addEventListener('change', (e) => {
    if (e.target.id === 'an-sev') V.renderSeverityNote();
    if (['od-origin', 'od-dest', 'od-background'].includes(e.target.id)) A.validateOd();
    if (e.target.id === 'weights-enabled') { S.form.weightsEnabled = e.target.checked; V.renderWeights(); }
    if (e.target.id === 'ev-facility' && e.target.value) {
      const dst = document.getElementById('ev-dst');
      if (dst) dst.value = e.target.value;
    }
    if (e.target.dataset?.runsel) {
      const id = e.target.dataset.runsel;
      if (e.target.checked) S.selected.add(id); else S.selected.delete(id);
      const cmp = document.getElementById('btn-compare');
      if (cmp) cmp.disabled = S.selected.size < 2;
    }
  });

  document.getElementById('traffic-table').addEventListener('click', (e) => {
    const th = e.target.closest('th[data-sort]');
    if (th) { V.setTrafficSort(th.dataset.sort); V.renderTraffic(); }
  });

  document.getElementById('btn-create-anomaly').onclick = () => A.createAnomaly();
  document.getElementById('btn-dispatch').onclick = () => A.dispatch();
  document.getElementById('btn-refresh-incidents').onclick = A.refreshIncidents;
  document.getElementById('btn-compare').onclick = A.compareSelected;
  document.getElementById('btn-demo-abort').onclick = A.abortDemo;
  document.getElementById('btn-export-json').onclick = () => {
    const ids = [...S.selected].join(',');
    window.location = `/api/export.json${ids ? `?ids=${ids}` : ''}`;
  };
  document.getElementById('btn-export-csv').onclick = () => {
    const ids = [...S.selected].join(',');
    window.location = `/api/export.csv${ids ? `?ids=${ids}` : ''}`;
  };
  document.getElementById('btn-selftest').onclick = async () => {
    const hint = document.getElementById('selftest-hint');
    hint.className = 'hint';
    hint.textContent = 'starting…';
    const res = await api('/api/selftest/start', { seconds: 180 });
    if (!res.ok) { hint.className = 'hint bad'; hint.textContent = res.reason || 'could not start'; return; }
    hint.className = 'hint ok';
    hint.textContent = 'publishing synthetic events for 3 minutes — open Live corridor';
    toast('Self-test running', 'Synthetic events only. Open Live corridor; anomaly injection and dispatch will answer too.', 'warn', 10000);
    await A.refreshStatus();
  };

  document.getElementById('btn-restart-api').onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    const hint = document.getElementById('key-hint');
    hint.className = 'hint';
    hint.textContent = 'restarting api-service…';
    const res = await api('/api/api/restart', {});
    btn.disabled = false;
    if (res.ok) {
      hint.className = 'hint ok';
      hint.textContent = 'api-service restarted — confirm and reject will work now.';
      toast('api-service restarted', 'Keys now match. The stream reconnects on its own.', 'ok');
    } else {
      hint.className = 'hint bad';
      hint.textContent = res.reason || 'could not restart api-service';
    }
    await A.refreshStatus();
    V.renderSettings();
  };

  document.getElementById('btn-save-key').onclick = async () => {
    const key = document.getElementById('api-key').value.trim();
    if (!key) return;
    const res = await api('/api/settings', { api_key: key });
    if (res.ok) {
      S.boot.config.api_key_source = res.api_key_source;
      V.renderSettings();
      toast('Key saved', 'Confirm and reject will use it from now on.', 'ok');
    }
  };

  // clicking a log line opens the full payload
  document.getElementById('eventlog').addEventListener('click', (e) => {
    const row = e.target.closest('[data-ev]');
    if (!row) return;
    // Index into the exact array renderLog() just drew (see views.js) rather
    // than recomputing the filter here -- a second copy of that filter had
    // drifted out of sync with the real one and could open the wrong event.
    const ev = V.getShownEvents()[Number(row.dataset.ev)];
    if (!ev) return;
    const existing = row.nextElementSibling;
    if (existing?.classList.contains('evjson')) { existing.remove(); return; }
    const pre = document.createElement('pre');
    pre.className = 'evjson logbox';
    pre.style.margin = '4px 14px';
    pre.textContent = JSON.stringify(ev.payload, null, 2);
    row.after(pre);
  });

  window.addEventListener('itms-picked', (e) => {
    document.querySelectorAll('[data-pick]').forEach((b) => b.classList.remove('picking'));
    V.renderPickBanner();
    toast('Road set', `${e.detail.label}: ${e.detail.edgeId}`, 'ok', 3000);
    A.scheduleValidate();
  });
  window.addEventListener('itms-incident', () => A.refreshIncidents());

  document.addEventListener('click', (e) => {
    if (e.target.id === 'pick-cancel') { S.pick = null; markDirty('pick'); }
  });
}

/* ── boot ─────────────────────────────────────────────────────── */
async function boot() {
  const boot = await api('/api/bootstrap');
  if (!boot || boot.ok === false || !boot.network) {
    document.getElementById('main').innerHTML =
      `<div class="view active"><div class="banner bad"><b>Could not load the corridor.</b><br>
        ${esc(boot?.reason || 'The control server answered, but not with the network data.')}</div></div>`;
    return;
  }
  S.boot = boot;
  S.form.demand = boot.repo.demand_levels.light?.present ? 'light' : 'medium';

  document.getElementById('navfoot').innerHTML =
    `${boot.network.counts.edges} edges · ${boot.network.counts.traffic_lights} signals<br>`
    + `${esc(boot.repo.repo.split('/').slice(-2).join('/'))}<br>read-only`;

  V.populateSelectors();
  wire();
  goto(location.hash.slice(1) || 'control');

  connect();
  await A.refreshStatus();
  await A.refreshRuns();
  V.renderPills(); V.renderRunClock(); V.renderNavBadges();
  renderView(S.view, true);

  setInterval(pollStatus, 1000);
  setInterval(pollLogs, 1400);
  setInterval(() => A.refreshRuns(), 6000);
  setInterval(pruneVehicles, 2000);
  setInterval(() => { if (S.view === 'map') V.renderMapRail(); }, 1000);
  requestAnimationFrame(frame);

  const r = boot.repo;
  if (!r.venv_python) {
    toast('The repo is not set up yet', 'No .venv in itms/. Run `make setup` there — nothing can start until it exists.', 'warn', 15000);
  }
}

boot();
