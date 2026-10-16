/* All rendering. One function per screen, each reading S and writing innerHTML.

   Deliberately plain: no virtual DOM, no templates. Every screen is small
   enough that a full re-render on a dirty flag is cheaper (in code you have to
   trust) than diffing, and the only high-frequency surface -- the map -- draws
   through Leaflet, not here. */

import {
  S, esc, num, dur, clock, ago, edgeLabel, isAnomalyActive, isEmergencyOpen,
} from './state.js';

/* ── top bar ──────────────────────────────────────────────────── */
export function renderPills() {
  const host = document.getElementById('pills');
  if (!host) return;
  const st = S.status?.stack;
  const p = [];
  const pill = (cls, label) => `<span class="pill ${cls}"><span class="dot"></span>${label}</span>`;

  if (!st) {
    p.push(pill('', 'connecting…'));
  } else {
    p.push(pill(st.redis?.ok ? 'ok' : 'bad', st.redis?.ok ? 'bus' : 'bus down'));
    p.push(pill(st.api?.ok ? 'ok' : 'bad', st.api?.ok ? 'api' : 'api down'));
    const sim = st.sim?.running;
    p.push(pill(sim ? 'live' : '', sim ? 'sim running' : 'sim idle'));
    const wsCls = { open: 'live', connecting: 'warn', closed: 'bad', error: 'bad', idle: '' }[S.ws.state] || '';
    p.push(pill(wsCls, S.ws.state === 'open' ? `stream ${num(S.ws.events)}` : `stream ${S.ws.state}`));
    if (st.gate?.running) p.push(pill('warn', 'gate running'));
  }
  host.innerHTML = p.join('');
}

export function renderRunClock() {
  const box = document.getElementById('runclock');
  const stopA = document.getElementById('btn-stop-run');
  const stopB = document.getElementById('btn-stop-run2');
  const running = !!S.status?.stack?.sim?.running;
  if (box) box.hidden = !running;
  if (stopA) stopA.hidden = !running;
  if (stopB) stopB.disabled = !running;
  if (!running || !box) return;
  const r = S.run || {};
  document.getElementById('rc-label').textContent =
    `${r.demand || '—'} · ${(r.controller || '—')}`;
  document.getElementById('rc-detail').textContent =
    `step ${num(r.step)} · sim ${dur(r.sim_time_s)} · ${num(r.steps_per_s, 1)} steps/s`;
}

export function renderNavBadges() {
  const counts = {
    anomalies: [...S.anomalies.values()].filter(isAnomalyActive).length,
    emergency: [...S.requests.values()].filter(isEmergencyOpen).length,
    incidents: S.incidents.filter((i) => String(i.state || i.status).toUpperCase() === 'CANDIDATE').length,
    signals: S.faults.length,
  };
  document.querySelectorAll('#sidenav button[data-go]').forEach((btn) => {
    const key = btn.dataset.go;
    btn.querySelector('.badge')?.remove();
    const n = counts[key];
    if (n) {
      const b = document.createElement('span');
      b.className = 'badge';
      b.textContent = n;
      btn.appendChild(b);
    }
  });
}

/* ── control room ─────────────────────────────────────────────── */
export function renderSetupBanner() {
  const host = document.getElementById('setup-banner');
  if (!host || !S.boot) return;
  const r = S.boot.repo;
  const problems = [];
  if (!r.repo_found) problems.push(`No repo at <code>${esc(r.repo)}</code>. This site expects to sit next to <code>itms/</code> inside CAPSTONE, or you can point it elsewhere with <code>ITMS_REPO=/path/to/itms</code>.`);
  if (!r.network_found) problems.push('The SUMO network is missing. Run <code>scenarios/networks/vijayawada/build.sh</code>.');
  if (r.venv_problem) problems.push(esc(r.venv_problem));
  else if (!r.venv_python) problems.push('No virtualenv in the repo. Run <code>make setup</code> inside <code>itms/</code> — nothing can be started until that exists.');
  else if (!r.sumo_binary) problems.push('No <code>sumo</code> binary found in the repo venv. A simulation needs SUMO; <code>make setup</code> installs the <code>eclipse-sumo</code> wheel.');
  if (!r.docker && !r.redis_server) problems.push('Neither Docker nor <code>redis-server</code> is available, so the bus cannot be started for you. Start Redis yourself and reload.');
  const missing = Object.entries(r.demand_levels).filter(([, m]) => !m.present).map(([k]) => k);
  if (missing.length) problems.push(`Demand files missing for: <b>${missing.join(', ')}</b>. Run <code>scenarios/demand/vijayawada/build_demand_levels.sh</code> (and <code>assign_vtypes.py</code> after it).`);

  if (!problems.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  host.className = 'banner warn';
  host.innerHTML = `<b>Before this can run:</b><ul>${problems.map((p) => `<li>${p}</li>`).join('')}</ul>`;
}

export function renderStack() {
  const host = document.getElementById('stackgrid');
  if (!host || !S.status) return;
  const st = S.status.stack;
  const cards = [
    {
      name: 'redis', title: 'Event bus',
      on: !!st.redis?.ok,
      state: st.redis?.ok ? 'reachable' : 'down',
      body: st.redis?.ok
        ? `Redis Streams at <code>${esc(st.redis.url)}</code>${st.redis.mode ? ` (${esc(st.redis.mode)})` : ''}. Everything travels over this — commands in, events out.`
        : `Not reachable at <code>${esc(st.redis?.url || '')}</code>. Started as the repo's own <code>docker compose</code> service when Docker is available.`,
      btns: st.redis?.ok
        ? [['stop', 'redis', 'ghost', 'Stop bus']]
        : [['start', 'redis', 'primary', 'Start bus']],
    },
    {
      name: 'api', title: 'api-service',
      on: !!st.api?.ok,
      state: st.api?.ok ? `${st.api.connected_clients ?? 0} client(s)` : 'down',
      body: st.api?.ok
        ? `Serving <code>/v1/commands</code>, <code>/v1/incidents</code> and the WebSocket on port ${st.api.port}.`
        : `Not answering on port ${st.api?.port}. Needed for every command this site sends and for the live stream.`,
      btns: st.api?.ok
        ? [['stop', 'api', 'ghost', 'Stop API']]
        : [['start', 'api', 'primary', 'Start API']],
    },
    {
      name: 'sim', title: 'Simulation',
      on: !!st.sim?.running,
      state: st.sim?.running ? 'running' : (st.sim?.exit_code != null ? `exited ${st.sim.exit_code}` : 'idle'),
      body: st.sim?.running
        ? `${esc(st.sim.meta?.engine || 'testlab')} · pid ${st.sim.pid} · up ${dur(st.sim.uptime_s)}`
        : 'Configure the traffic below and press Start run.',
      btns: st.sim?.running ? [['stop', 'sim', 'danger', 'Stop run']] : [],
    },
  ];

  host.innerHTML = cards.map((c) => `
    <div class="stackcard">
      <div class="sc-top">
        <h5>${esc(c.title)}</h5>
        <span class="sc-state ${c.on ? 'on' : 'off'}">${esc(c.state)}</span>
      </div>
      <p>${c.body}</p>
      <div class="sc-btns">
        ${c.btns.map(([act, what, kind, label]) =>
    `<button class="btn ${kind} sm" data-stack="${act}:${what}">${esc(label)}</button>`).join('')}
      </div>
    </div>`).join('')
    + `<div class="stackcard">
        <div class="sc-top"><h5>Everything</h5><span class="sc-state">shortcut</span></div>
        <p>Bring the bus and the API up together. Safe to press when they are already up — it leaves running services alone.</p>
        <div class="sc-btns">
          <button class="btn sm" data-stack="start:all">Start bus + API</button>
          <button class="btn ghost sm" data-stack="stop:all">Stop everything</button>
        </div>
      </div>`;
}

export function renderDemandSeg() {
  const host = document.getElementById('demand-seg');
  if (!host || !S.boot) return;
  const levels = S.boot.repo.demand_levels;
  const opts = [
    ['light', 'Light', levels.light],
    ['medium', 'Medium', levels.medium],
    ['heavy', 'Heavy', levels.heavy],
  ].map(([id, label, meta]) => `
    <button class="segopt ${S.form.demand === id ? 'on' : ''} ${meta.present ? '' : 'miss'}"
            data-demand="${id}" role="radio" aria-checked="${S.form.demand === id}"
            ${meta.present ? '' : 'disabled title="demand file not built"'}>
      <b>${label} traffic</b>
      <em>≈${num(meta.approx_vehicles)} vehicles · one every ${meta.period_s}s
      ${meta.present ? '' : '<br>FILE MISSING'}</em>
    </button>`).join('');

  host.innerHTML = opts + `
    <button class="segopt ${S.form.demand === 'custom' ? 'on' : ''}" data-demand="custom"
            role="radio" aria-checked="${S.form.demand === 'custom'}">
      <b>Custom O→D</b>
      <em>you choose the count, the start road and the destination</em>
    </button>`;

  const custom = document.getElementById('custom-od');
  if (custom) custom.hidden = S.form.demand !== 'custom';
}

export function renderOptionRows() {
  const cHost = document.getElementById('controller-opts');
  const eHost = document.getElementById('engine-opts');
  if (!S.boot) return;
  if (cHost) {
    cHost.innerHTML = S.boot.controllers.map((c) => `
      <button class="opt ${S.form.controller === c.id ? 'on' : ''}" data-controller="${esc(c.id)}"
              role="radio" aria-checked="${S.form.controller === c.id}">
        <b>${esc(c.label)}</b><span>${esc(c.note)}</span>
      </button>`).join('');
  }
  if (eHost) {
    eHost.innerHTML = S.boot.engines.map((e) => `
      <button class="opt ${S.form.engine === e.id ? 'on' : ''}" data-engine="${esc(e.id)}"
              role="radio" aria-checked="${S.form.engine === e.id}">
        <b>${esc(e.label)}</b><span>${esc(e.note)}</span>
      </button>`).join('');
  }
}

/* itms_domain.routing.EmergencyRoutingConfig's six weights, exposed as an
   opt-in panel: off by default, so a run started without touching it behaves
   exactly as before. Only meaningful for the testlab engine (see server.py's
   start_run), which the option-row toggle above already warns about when a
   repo entry point is picked. */
export function renderWeights() {
  const toggle = document.getElementById('weights-enabled');
  const panel = document.getElementById('weights-panel');
  if (!toggle || !panel || !S.boot?.route_cost_weights) return;
  toggle.checked = !!S.form.weightsEnabled;
  panel.hidden = !S.form.weightsEnabled;
  // This view redraws on every 1s status poll while it's on screen. Rebuilding
  // these inputs' innerHTML every time would blow away focus and the cursor
  // position mid-keystroke -- build them once and just flip `hidden` after
  // that; the input listener in app.js already keeps S.form.weights (and the
  // DOM values collectRunConfig reads at submit time) in sync from here on.
  if (panel.dataset.built === '1') return;
  panel.dataset.built = '1';
  panel.innerHTML = S.boot.route_cost_weights.map((f) => `
    <label class="fld">
      <span>${esc(f.label)}<em>${esc(f.note)}</em></span>
      <input type="number" step="0.05" min="0" id="w-${esc(f.id)}"
             value="${S.form.weights[f.id] ?? f.default}">
    </label>`).join('');
}

export function renderRunLive() {
  const host = document.getElementById('run-live');
  if (!host) return;
  const r = S.run;
  const running = !!S.status?.stack?.sim?.running;
  if (!r || (!running && !['finished', 'stopped', 'failed'].includes(r.state))) {
    // The backend clears the "active run" a moment after a run ends, so the
    // live stats panel below is only on screen for about a second after a
    // failure -- easy to miss entirely. Fall back to the run history's own
    // record of it (S.runs, refreshed independently every few seconds) so a
    // failure stays visible here instead of silently reverting to "nothing
    // has run yet", which was actively misleading right after a real run.
    const last = S.runs[0];
    if (last && ['finished', 'stopped', 'failed'].includes(last.state)) {
      const cls = { finished: 'ok', failed: 'bad', stopped: 'warn' }[last.state] || '';
      host.innerHTML = `<div class="card">
        <p class="sub" style="margin:0 0 8px">Last run: <b>${esc(last.label || last.id)}</b>
          <span class="chip ${cls}">${esc(last.state)}</span></p>
        ${last.error ? `<p class="sub" style="margin:0 0 8px;color:#F0A3AB"><b>Error:</b> ${esc(last.error)}</p>` : ''}
        <p class="sub" style="margin:0">Pick a traffic level and press <b>Start run</b> to go again.</p>
      </div>`;
      return;
    }
    host.innerHTML = `<div class="card"><p class="sub" style="margin:0">Nothing has run yet. Pick a traffic level and press <b>Start run</b> — this panel then shows the simulation's own counters, live.</p></div>`;
    return;
  }

  const tiles = [];
  const t = (em, val, cls = '', sub = '', bar = null) => tiles.push(`
    <div class="tile ${cls}"><em>${em}</em><b>${val}</b>
      ${sub ? `<div class="sub2">${sub}</div>` : ''}
      ${bar !== null ? `<div class="bar ${bar.cls || ''}"><i style="width:${Math.min(100, bar.pct)}%"></i></div>` : ''}
    </div>`);

  const stateCls = { running: 'accent', finished: 'good', stopped: 'warn', failed: 'bad', starting: 'warn' }[r.state] || '';
  t('state', esc(r.state || '—'), stateCls, `${esc(r.demand || '')} · ${esc(r.controller || '')}`);
  t('sim clock', dur(r.sim_time_s), '', `step ${num(r.step)}${r.max_steps ? ` / ${num(r.max_steps)}` : ''}`,
    r.max_steps ? { pct: (r.step / r.max_steps) * 100 } : null);
  t('vehicles now', num(r.vehicles?.active), '', `${num(r.vehicles?.departed_total)} in, ${num(r.vehicles?.arrived_total)} out`);
  t('mean speed', `${num(r.network?.mean_speed_mps, 1)}<small> m/s</small>`, '',
    `${num(r.network?.total_halting)} halted`);
  t('wall clock', dur(r.wall_s), '', `${num(r.steps_per_s, 1)} steps/s`);

  if (r.od) {
    const o = r.od;
    const pct = o.target_arrivals ? (o.arrived / o.target_arrivals) * 100 : 0;
    t('arrivals vs target', `${num(o.arrived)}<small> / ${num(o.target_arrivals)}</small>`,
      o.target_met ? 'good' : (r.state === 'finished' ? 'bad' : ''),
      `${num(o.in_transit)} in transit · ${num(o.not_yet_departed)} waiting to depart`,
      { pct, cls: o.target_met ? 'good' : (pct > 60 ? 'warn' : 'bad') });
    t('mean trip time', o.mean_travel_s ? dur(o.mean_travel_s) : '—', '',
      `${esc(o.origin || '')} → ${esc(o.destination || '')}`);
  }

  const c = r.counters || {};
  t('commands drained', num(c.commands_drained), '', 'operator actions the sim applied');
  if (r.summary) {
    t('interlock violations', num(r.summary.interlock_violations ?? 0),
      (r.summary.interlock_violations ?? 0) > 0 ? 'bad' : 'good', 'Layer-0 safety kernel');
  }

  const notes = [];
  if (r.incident_detector) {
    notes.push(`<b>M6 detector:</b> ${esc(r.incident_detector)} — real code, nothing to detect until a trained model is dropped into <code>scripts/results/m6_artifacts/</code>.`);
  }
  if (r.route_cost_weights) {
    const defs = S.boot?.route_cost_weights || [];
    const changed = defs.filter((f) => Math.abs((r.route_cost_weights[f.id] ?? f.default) - f.default) > 1e-9);
    if (changed.length) {
      notes.push('<b>Custom route-cost weights:</b> ' + changed.map((f) =>
        `${esc(f.label)} ${num(r.route_cost_weights[f.id], 2)} (default ${num(f.default, 2)})`).join(', '));
    }
  }
  if (r.note) notes.push(esc(r.note));
  if (r.error) notes.push(`<b>Error:</b> <span style="color:#F0A3AB">${esc(r.error)}</span>`);

  let metricsHtml = '';
  if (r.metrics && !r.metrics.error) {
    const m = r.metrics;
    metricsHtml = `
      <div class="card"><h4>Scored KPIs <span class="chip">tripinfo · ${num(m.warmup_s)}s warm-up</span></h4>
        <p class="sub">Computed by the repo's own <code>control.metrics</code> from SUMO's <code>tripinfo</code> output — the same code path the gate scripts use.</p>
        <div class="tiles">
          <div class="tile"><em>person delay</em><b>${num(m.person_delay_s)}<small> p·s</small></b></div>
          <div class="tile"><em>person throughput</em><b>${num(m.person_throughput_per_hour)}<small> /h</small></b></div>
          <div class="tile"><em>mean wait</em><b>${num(m.wait_mean_s, 1)}<small> s</small></b></div>
          <div class="tile"><em>wait p95</em><b>${num(m.wait_p95_s, 1)}<small> s</small></b></div>
          <div class="tile"><em>worst wait</em><b>${num(m.wait_max_s, 1)}<small> s</small></b></div>
          <div class="tile"><em>stops / vehicle</em><b>${num(m.stops_per_vehicle, 2)}</b></div>
          <div class="tile"><em>trips scored</em><b>${num(m.n_trips_scored)}<small> / ${num(m.n_trips_total)}</small></b></div>
        </div>
      </div>`;
  } else if (r.metrics?.error) {
    notes.push(`<b>KPI scoring failed:</b> ${esc(r.metrics.error)}`);
  }

  host.innerHTML = `<div class="tiles">${tiles.join('')}</div>`
    + (notes.length ? `<div class="banner">${notes.join('<br>')}</div>` : '')
    + metricsHtml;
}

export function renderOdCheck(result) {
  const host = document.getElementById('od-check');
  if (!host) return;
  if (!result) { host.innerHTML = '<span class="hint">Pick an origin and a destination to check the pair.</span>'; return; }
  if (!result.ok) {
    host.innerHTML = `<span class="hint bad">${esc(result.reason || 'that pair will not work')}</span>`;
    return;
  }
  const warn = result.oversaturated
    ? `<div class="banner warn" style="margin:10px 0 0"><b>That release rate is above what one approach can discharge.</b> One vehicle every ${num(result.headway_s, 1)}s is faster than saturation flow (~one per 2s per lane), so a queue will build at the origin and the target is probably unreachable. Widen the release window or lower the count — unless testing exactly that is the point.</div>`
    : '';
  host.innerHTML = `
    <div class="kv">
      <span><i>route</i> ${result.route.length} edges</span>
      <span><i>distance</i> ${num(result.length_m)} m</span>
      <span><i>free-flow</i> ${num(result.free_flow_s)} s</span>
      <span><i>signals crossed</i> ${result.n_signals}</span>
      <span><i>release headway</i> ${num(result.headway_s, 1)} s</span>
    </div>
    <div class="sub" style="margin:8px 0 0">Path: <span class="mono">${result.route.map(esc).join(' → ')}</span></div>
    ${warn}`;
}

/* ── map rail ─────────────────────────────────────────────────── */
export function renderMapRail() {
  const host = document.getElementById('maprail');
  if (!host) return;
  const r = S.run || {};
  const byType = {};
  for (const v of S.vehicles.values()) byType[v.type || 'unknown'] = (byType[v.type || 'unknown'] || 0) + 1;
  const active = [...S.anomalies.values()].filter(isAnomalyActive);
  const openReq = [...S.requests.values()].filter(isEmergencyOpen);

  const kv = (k, v) => `<div class="railkv"><span>${k}</span><b>${v}</b></div>`;
  host.innerHTML = `
    <div class="railsec"><h6>Run</h6>
      ${kv('state', esc(r.state || 'idle'))}
      ${kv('demand / controller', `${esc(r.demand || '—')} / ${esc(r.controller || '—')}`)}
      ${kv('sim clock', dur(r.sim_time_s))}
      ${kv('speed', `${num(r.steps_per_s, 1)} steps/s`)}
    </div>
    <div class="railsec"><h6>On the map</h6>
      ${kv('vehicles streaming', num(S.vehicles.size))}
      ${Object.entries(byType).sort((a, b) => b[1] - a[1])
      .map(([t, n]) => kv(`&nbsp;&nbsp;${esc(t.replace(/^(veh|od)_/, ''))}`, num(n))).join('')}
      ${kv('signals commanded', num(S.signals.size))}
      ${kv('active anomalies', num(active.length))}
      ${kv('open requests', num(openReq.length))}
    </div>
    ${active.length ? `<div class="railsec"><h6>Anomalies</h6>${active.map((a) => `
      <div class="railkv"><span>${esc(a.anomaly_type)}<br><span class="mono" style="font-size:10px">${esc(a.edge_id)}</span></span>
      <b><span class="chip ${sevChip(a.severity)}">${esc(a.severity)}</span></b></div>`).join('')}</div>` : ''}
    ${openReq.length ? `<div class="railsec"><h6>Emergency</h6>${openReq.map((x) => `
      <div class="railkv"><span>${esc(x.vehicle_kind || 'unit')}<br><span class="mono" style="font-size:10px">${esc(x.request_id?.slice(0, 8))}</span></span>
      <b>${esc(x.state)}</b></div>`).join('')}</div>` : ''}
    <div class="railsec"><h6>Stream</h6>
      ${kv('socket', esc(S.ws.state))}
      ${kv('events received', num(S.ws.events))}
      ${kv('last event', S.ws.lastAt ? `${((Date.now() - S.ws.lastAt) / 1000).toFixed(1)}s ago` : '—')}
    </div>`;
}

export function renderPickBanner() {
  const el = document.getElementById('pickbanner');
  if (!el) return;
  if (!S.pick) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<span>Click a road on the map to set <b>${esc(S.pick.label)}</b>.</span>
    <button id="pick-cancel">Cancel</button>`;
}

const sevChip = (s) => ({ low: 'warn', medium: 'warn', high: 'bad', blocked: 'bad' }[String(s).toLowerCase()] || '');

/* ── signals ──────────────────────────────────────────────────── */
export function renderSignals() {
  const tiles = document.getElementById('signal-tiles');
  const table = document.getElementById('signal-table');
  const ladder = document.getElementById('ladder');
  const faults = document.getElementById('faultlist');
  if (!tiles) return;

  const totalChanges = Object.values(S.sourceCounts).reduce((a, b) => a + b, 0);
  const preempt = S.sourceCounts.corridor_preemption || 0;
  const rejected = S.faults.filter((f) => f.type === 'interlock_rejected').length;
  const violations = S.run?.summary?.interlock_violations;

  tiles.innerHTML = `
    <div class="tile"><em>junctions commanded</em><b>${num(S.signals.size)}<small> / ${num(Object.keys(S.boot?.network?.traffic_lights || {}).length)}</small></b></div>
    <div class="tile"><em>phase changes</em><b>${num(totalChanges)}</b></div>
    <div class="tile ${preempt ? 'good' : ''}"><em>preemptions granted</em><b>${num(preempt)}</b><div class="sub2">rung 3 · green corridor</div></div>
    <div class="tile ${rejected ? 'warn' : ''}"><em>plans rejected</em><b>${num(rejected)}</b><div class="sub2">interlocks said no</div></div>
    <div class="tile ${violations ? 'bad' : 'good'}"><em>interlock violations</em><b>${violations == null ? '—' : num(violations)}</b><div class="sub2">must stay 0</div></div>
    <div class="tile ${S.faults.length ? 'warn' : ''}"><em>fault events</em><b>${num(S.faults.length)}</b></div>`;

  const tls = S.boot?.network?.traffic_lights || {};
  const rows = Object.keys(tls).sort().map((id) => {
    const s = S.signals.get(id);
    const inCorridor = [...S.corridors.values()].some(
      (c) => c.status === 'ACTIVE' && (c.reservations || []).some((r) => r.intersection_id === id),
    );
    return `<tr>
      <td class="id">${esc(id)}</td>
      <td class="num">${num(tls[id].n_phases)}</td>
      <td>${s?.phase ? `<b>${esc(s.phase)}</b>` : '<span class="chip dim">—</span>'}</td>
      <td>${s?.source ? `<span class="chip ${s.source === 'corridor_preemption' ? 'ok' : 'cy'}">${esc(s.source)}</span>` : '<span class="chip dim">not commanded yet</span>'}</td>
      <td class="num">${num(s?.changes || 0)}</td>
      <td>${inCorridor ? '<span class="chip ok">reserved</span>' : ''}
          ${s?.faulted ? `<span class="chip bad">${esc(s.faulted)}</span>` : ''}</td>
      <td class="id">${s?.at ? clock(s.at) : ''}</td>
    </tr>`;
  });
  table.innerHTML = `<thead><tr>
      <th>Junction</th><th>Phases</th><th>Live phase</th><th>Source rung</th>
      <th>Changes</th><th>Flags</th><th>Last</th></tr></thead>
    <tbody>${rows.join('') || '<tr><td class="empty" colspan="7">No signal events yet — start a run.</td></tr>'}</tbody>`;

  const rungs = [
    [1, 'Hardware / safety faults', 'failsafe', S.faults.length],
    [2, 'Manual operator override', 'manual_override', S.sourceCounts.manual_override || 0],
    [3, 'Corridor preemption', 'corridor_preemption', preempt],
    [4, 'Adaptive optimiser', null, (S.sourceCounts.acamp || 0) + (S.sourceCounts.camp || 0)],
    [5, 'Fixed-time fallback', null, (S.sourceCounts.fixed_time || 0) + (S.sourceCounts.webster_fixed_time || 0)],
  ];
  ladder.innerHTML = rungs.map(([n, name, , count]) => `
    <div class="rung ${count ? 'hot' : 'idle'}">
      <span class="n">${n}</span><span class="nm">${esc(name)}</span>
      <span class="ct">${count ? `${num(count)} decision(s)` : 'quiet'}</span>
    </div>`).join('')
    + `<p class="sub" style="margin:10px 0 0">Only the Signal Controller commands a signal. Everything at rungs 3–5 proposes, and every proposal is checked by the same Layer-0 interlocks — a corridor request that would truncate min-green is rejected and the junction falls back.</p>`;

  faults.innerHTML = S.faults.length
    ? S.faults.slice(0, 40).map((f) => `<div class="faultrow">
        <b>${esc(f.type)}</b> · ${esc(f.id)} · ${clock(f.at)}<br>${esc(f.detail || '')}</div>`).join('')
    : '<div class="faultrow ok">No faults and no rejected plans. That is the expected state.</div>';
}

/* ── traffic ──────────────────────────────────────────────────── */
let trafficSort = { key: 'occ', asc: false };
export function setTrafficSort(key) {
  if (trafficSort.key === key) trafficSort.asc = !trafficSort.asc;
  else trafficSort = { key, asc: false };
}

export function renderTraffic() {
  const tiles = document.getElementById('traffic-tiles');
  const table = document.getElementById('traffic-table');
  if (!tiles || !S.boot) return;

  const edges = S.boot.network.edges;
  const rows = Object.keys(edges).map((id) => {
    const runEdge = S.run?.network?.edges?.[id];
    const a = S.approach.get(id);
    const anomaly = [...S.anomalies.values()].find((x) => isAnomalyActive(x) && x.edge_id === id);
    return {
      id,
      name: edges[id].name || '',
      lanes: edges[id].num_lanes,
      length: edges[id].length_m,
      limit: edges[id].speed_limit_mps,
      n: runEdge?.n ?? (a ? Math.round(a.q_pcu ?? 0) : null),
      occ: runEdge?.occ ?? a?.occupancy ?? null,
      halting: runEdge?.halting ?? null,
      speed: runEdge?.speed ?? null,
      arrival: a?.arrival ?? null,
      anomaly,
      signalised: (edges[id].signalised_entry_tls || []).length > 0,
    };
  });

  const withData = rows.filter((r) => r.n != null);
  const totalVeh = withData.reduce((s, r) => s + (r.n || 0), 0);
  const totalHalt = withData.reduce((s, r) => s + (r.halting || 0), 0);
  const worst = withData.slice().sort((a, b) => (b.occ || 0) - (a.occ || 0))[0];
  const speeds = withData.filter((r) => r.n > 0 && r.speed != null);
  const meanSpeed = speeds.length ? speeds.reduce((s, r) => s + r.speed, 0) / speeds.length : null;

  tiles.innerHTML = `
    <div class="tile"><em>vehicles on network</em><b>${num(totalVeh)}</b><div class="sub2">across ${num(withData.length)} reporting edges</div></div>
    <div class="tile ${totalHalt > totalVeh * 0.35 ? 'warn' : ''}"><em>halted</em><b>${num(totalHalt)}</b><div class="sub2">${totalVeh ? num((totalHalt / totalVeh) * 100, 0) : 0}% of them</div></div>
    <div class="tile"><em>mean edge speed</em><b>${num(meanSpeed, 1)}<small> m/s</small></b></div>
    <div class="tile ${worst && worst.occ > 0.2 ? 'warn' : ''}"><em>worst occupancy</em><b>${num((worst?.occ || 0) * 100, 1)}<small>%</small></b><div class="sub2">${esc(worst?.id || '—')}</div></div>
    <div class="tile"><em>signalised edges</em><b>${num(rows.filter((r) => r.signalised).length)}</b></div>
    <div class="tile ${[...S.anomalies.values()].some(isAnomalyActive) ? 'bad' : ''}"><em>edges with anomaly</em><b>${num(rows.filter((r) => r.anomaly).length)}</b></div>`;

  const dir = trafficSort.asc ? 1 : -1;
  rows.sort((a, b) => {
    const k = trafficSort.key;
    const av = a[k] ?? -1; const bv = b[k] ?? -1;
    if (typeof av === 'string') return av.localeCompare(bv) * dir;
    return (av - bv) * dir;
  });

  const cols = [
    ['id', 'Edge'], ['name', 'Street'], ['n', 'Vehicles'], ['occ', 'Occupancy'],
    ['halting', 'Halted'], ['speed', 'Mean speed'], ['arrival', 'Arrivals/s'],
    ['lanes', 'Lanes'], ['length', 'Length'],
  ];
  table.innerHTML = `<thead><tr>${cols.map(([k, label]) =>
    `<th data-sort="${k}" class="${trafficSort.key === k ? `sorted ${trafficSort.asc ? 'asc' : ''}` : ''}">${label}</th>`).join('')}<th>Flags</th></tr></thead>
    <tbody>${rows.map((r) => `<tr>
      <td class="id">${esc(r.id)}</td>
      <td>${esc(r.name || '—')}</td>
      <td class="num">${r.n == null ? '—' : num(r.n)}</td>
      <td class="num">${r.occ == null ? '—' : `${num(r.occ * 100, 1)}%`}</td>
      <td class="num">${r.halting == null ? '—' : num(r.halting)}</td>
      <td class="num">${r.speed == null ? '—' : num(r.speed, 1)}</td>
      <td class="num">${r.arrival == null ? '—' : num(r.arrival, 2)}</td>
      <td class="num">${num(r.lanes)}</td>
      <td class="num">${num(r.length)}</td>
      <td>${r.signalised ? '<span class="chip dim">signal</span> ' : ''}${r.anomaly ? `<span class="chip ${sevChip(r.anomaly.severity)}">${esc(r.anomaly.anomaly_type)}</span>` : ''}</td>
    </tr>`).join('')}</tbody>`;
}

/* ── event log ────────────────────────────────────────────────── */
// The rows renderLog() last drew, in the same order as their on-screen
// data-ev="i" index. app.js's row-click handler (which opens a row's raw
// JSON) reads this instead of recomputing the same filter itself -- two
// independent copies of this predicate had drifted apart (one included the
// event's `key` in the text search, the other didn't), which meant clicking
// a row while a key-only search match was in the list could open the wrong
// event's payload. One source of truth here removes that whole class of bug.
let lastShownEvents = [];
export function getShownEvents() { return lastShownEvents; }

export function renderLog() {
  const filters = document.getElementById('event-filters');
  const logEl = document.getElementById('eventlog');
  if (!filters || !logEl) return;

  const types = Object.keys(S.typeCounts).sort();
  filters.innerHTML = types.map((t) => `
    <button class="fchip ${S.logFilter.hidden.has(t) ? '' : 'on'}" data-etype="${esc(t)}">
      ${esc(t)}<span class="n">${num(S.typeCounts[t])}</span></button>`).join('')
    + `<input type="search" id="event-q" placeholder="filter text…" value="${esc(S.logFilter.q)}">
       <button class="fchip" data-etype="__all">show all</button>
       <button class="fchip" data-etype="__none">hide all</button>`;

  const q = S.logFilter.q.toLowerCase();
  const shown = S.events.filter((e) => !S.logFilter.hidden.has(e.type)
    && (!q || (e.type + ' ' + e.line + ' ' + (e.key || '')).toLowerCase().includes(q)))
    .slice(0, 400);
  lastShownEvents = shown;

  logEl.innerHTML = shown.length
    ? shown.map((e, i) => `<div class="ev ${e.cat}" data-ev="${i}">
        <span class="t">${clock(e.at)}</span>
        <span class="ty">${esc(e.type)}</span>
        <span class="bd">${esc(e.line)}</span></div>`).join('')
    : `<div style="padding:24px;text-align:center;color:#5B686D">${
      S.ws.state === 'open'
        ? 'Stream is open. Nothing matches the current filters — vehicle positions and approach state are hidden by default because they are a firehose.'
        : `Stream is ${esc(S.ws.state)}. Start the bus and api-service, then a run.`}</div>`;
}

/* ── anomalies ────────────────────────────────────────────────── */
export function renderAnomalies() {
  const host = document.getElementById('anomaly-list');
  if (!host) return;
  const list = [...S.anomalies.values()].sort((a, b) => (b.updated_at_ms || b.at || 0) - (a.updated_at_ms || a.at || 0));
  if (!list.length) {
    host.innerHTML = `<p class="sub" style="margin:0">Nothing injected yet. An anomaly needs a run in progress — the command is drained by the simulation loop, so with nothing running it sits on the bus unread.</p>`;
    return;
  }
  host.innerHTML = list.map((a) => {
    const on = isAnomalyActive(a);
    // anomaly_updated.avsc: estimated_impact (0..1, fed to the routing cost
    // model) and expires_at_ms (set only when the create command carried a
    // duration_s) are both real fields -- shown below rather than assumed
    // away, now that this panel is wired to the real schema.
    return `<div class="rowcard ${on ? 'on' : ''}">
      <div class="rc-head">
        <h5>${esc((a.anomaly_type || '').replace(/_/g, ' '))}</h5>
        <span class="chip ${sevChip(a.severity)}">${esc(a.severity)}</span>
        <div class="rc-meta">
          <span class="chip ${on ? 'ok' : 'dim'}">${esc(a.status)}</span>
          <span class="chip">source ${esc((a.source || '').toLowerCase())}</span>
        </div>
      </div>
      <div class="kvgrid">
        <div><i>edge</i>${esc(a.edge_id)}</div>
        <div><i>lane</i>${esc(a.lane_id || 'whole edge')}</div>
        <div><i>impact</i>${num(a.estimated_impact, 2)}</div>
        <div><i>expires</i>${a.expires_at_ms ? clock(a.expires_at_ms) : 'until cleared'}</div>
        <div><i>id</i>${esc(String(a.anomaly_id).slice(0, 8))}</div>
        <div><i>by</i>${esc(a.operator || '—')}</div>
      </div>
      ${a.detail ? `<p class="sub" style="margin:6px 0 0">${esc(a.detail)}</p>` : ''}
      ${on ? `<div class="rc-btns">
        <button class="btn ok sm" data-clear-anomaly="${esc(a.anomaly_id)}" data-resolution="RESOLVED">Resolve</button>
        <button class="btn danger sm" data-clear-anomaly="${esc(a.anomaly_id)}" data-resolution="CANCELLED">Cancel (mistake)</button>
        <button class="btn ghost sm" data-flyto="${esc(a.edge_id)}">Show on map</button>
      </div>` : ''}
    </div>`;
  }).join('');
}

/* ── emergency ────────────────────────────────────────────────── */
export function renderEmergency() {
  const list = document.getElementById('request-list');
  const detail = document.getElementById('route-detail');
  if (!list) return;

  const reqs = [...S.requests.values()].sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  if (!reqs.length) {
    list.innerHTML = `<p class="sub" style="margin:0">No dispatches yet. A request needs a run in progress — the router samples live traffic and active anomalies from the simulation, so it has nothing to route against otherwise.</p>`;
    detail.innerHTML = '';
    return;
  }

  // emergency_request_updated.avsc's real state vocabulary (upper-case) --
  // see state.js's EMERGENCY_OPEN_STATES/EMERGENCY_TERMINAL_STATES doc.
  const stateChip = (s) => ({
    CREATED: '', ROUTING: 'warn', ROUTE_READY: 'ok', GREEN_CORRIDOR_ACTIVE: 'ok',
    IN_TRANSIT: 'ok', COMPLETED: 'dim', CANCELLED: 'bad',
  }[s] || '');

  let focus = null;
  list.innerHTML = reqs.map((r, i) => {
    const ev = [...S.evs.values()].find((e) => e.vehicle_id === r.vehicle_id);
    const corridor = r.green_corridor_id ? S.corridors.get(r.green_corridor_id) : null;
    const open = isEmergencyOpen(r);
    if (i === 0 && r.route) focus = r;
    return `<div class="rowcard ${open ? 'on' : ''}">
      <div class="rc-head">
        <h5>${esc((r.vehicle_kind || 'unit').toLowerCase())} · ${esc(String(r.request_id).slice(0, 8))}</h5>
        <div class="rc-meta">
          <span class="chip ${stateChip(r.state)}">${esc(r.state)}</span>
          ${r.eta_s != null ? `<span class="chip">eta ~${num(r.eta_s, 0)}s</span>` : ''}
        </div>
      </div>
      <p>${esc(r.vehicle_id || '—')} · ${esc(edgeLabel(r.source_edge))} → ${esc(edgeLabel(r.destination_edge))}${r.detail ? ` · ${esc(r.detail)}` : ''}</p>
      <div class="kvgrid">
        <div><i>actor</i>${esc(r.actor || '—')}</div>
        <div><i>audit chain</i><span class="mono" title="${esc(r.chain_hash || '')}">${esc(String(r.chain_hash || '').slice(0, 10))}…</span></div>
      </div>
      ${ev ? `<div class="kvgrid">
        <div><i>vehicle status</i>${esc((ev.status || '').toLowerCase())}</div>
        <div><i>speed</i>${num(ev.speed_mps, 1)} m/s</div>
        <div><i>progress</i>${num((ev.route_progress || 0) * 100, 0)}%</div>
      </div>` : ''}
      ${corridor ? corridorBlock(corridor) : ''}
      <div class="rc-btns">
        ${r.state === 'ROUTE_READY' ? `<button class="btn ok sm" data-corridor="${esc(r.request_id)}">Activate green corridor</button>` : ''}
        ${['ROUTE_READY', 'IN_TRANSIT'].includes(r.state) ? `<button class="btn ghost sm" data-recalc="${esc(r.request_id)}">Recalculate</button>` : ''}
        ${open ? `<button class="btn danger sm" data-cancel-req="${esc(r.request_id)}">Cancel</button>` : ''}
        ${r.route ? `<button class="btn ghost sm" data-showroute="${esc(r.request_id)}">Why this route</button>` : ''}
      </div>
    </div>`;
  }).join('');

  // Continuous re-routing is real (EmergencyController._monitor_routes,
  // sim_service/live/emergency_control.py) and runs server-side every 3s
  // against every ROUTE_READY/IN_TRANSIT request -- it triggers on a BLOCKED/
  // severe anomaly ahead, or on a materially cheaper replan, subject to a
  // 30s cooldown and a 3% minimum-progress gate. This log is populated from
  // `actor: "system:monitor"` transitions seen on the stream (stream.js),
  // not from a separate "reroute" event -- there isn't one.
  const rerouteBlock = `
    <div class="card"><h4>Automatic re-routes</h4>
      <p class="sub">Server-side monitor (every 3s, 30s cooldown, 3% minimum progress) — reroutes on a blocked/severe anomaly ahead or a materially cheaper replan. Lines below are transitions whose actor was <span class="mono">system:monitor</span> or whose detail mentions a reroute.</p>
      ${S.rerouteLog.length
      ? S.rerouteLog.map((x) => `<div class="faultrow ok">${clock(x.at)} · ${esc(String(x.request).slice(0, 8))} · ${esc(x.detail)}</div>`).join('')
      : '<div class="faultrow">None seen yet on this run.</div>'}
    </div>`;

  const chosen = (S.showRoute && S.requests.get(S.showRoute)) || focus;
  detail.innerHTML = (chosen && chosen.route ? routeExplain(chosen) : '') + rerouteBlock;
}

function corridorBlock(c) {
  // green_corridor_updated.avsc: a full snapshot each time (status +
  // reservations + peak_concurrency), not a per-junction delta -- so this
  // just renders the latest one, keyed by corridor_id in stream.js.
  const statusChip = { PROPOSED: 'warn', ACTIVE: 'ok', RESTORING: 'warn', COMPLETED: 'dim', CANCELLED: 'bad' }[c.status] || '';
  const res = c.reservations || [];
  return `<div class="junctionchips">
      <span class="chip ${statusChip}">corridor ${esc((c.status || '').toLowerCase())}</span>
      <span class="chip">last event ${esc(c.event || '—')}</span>
      <span class="chip">peak concurrency ${num(c.peak_concurrency || 0)}</span>
      ${res.map((r) => `<span class="chip cy" title="opens ${clock(r.open_at_ms)}, closes ${clock(r.close_at_ms)}">${esc(String(r.intersection_id).slice(0, 14))}</span>`).join('')}
    </div>`;
}

/* The six cost fields are NOT in the same units: `RouteCostModel.edge_cost`
   returns travel time and signal delay as raw seconds and the other four as
   already-weighted, already-normalised numbers. Drawing them on one bar chart
   as-is makes travel time swamp everything and means nothing. So the raw
   seconds are converted the way the cost model does -- divided by
   `travel_time_ref_s` and multiplied by their weight -- and the bars show the
   weighted contribution, which is what the planner actually minimised. The sum
   is checked against the recorded `route_score` and any mismatch is shown
   rather than hidden. */
const TRAVEL_TIME_REF_S = 60.0; // EmergencyRoutingConfig.travel_time_ref_s default

function costTerms(rt) {
  // weights_used's real keys are EmergencyRoutingConfig's own field names
  // (travel_time_weight, congestion_weight, anomaly_weight, signal_delay_weight,
  // disruption_weight, reliability_weight) -- verified against
  // services/sim-service/tests/live/test_emergency_control.py's own assertion
  // (`set(r["weights_used"]) >= {"anomaly_weight", "travel_time_weight"}`).
  const w = rt.weights_used || {};
  const wt = (k, d) => (typeof w[`${k}_weight`] === 'number' ? w[`${k}_weight`] : d);
  return [
    { label: 'travel time', raw: rt.cost_travel_time_s, unit: 's',
      weight: wt('travel_time', 1.0),
      contribution: wt('travel_time', 1.0) * (Number(rt.cost_travel_time_s || 0) / TRAVEL_TIME_REF_S),
      note: `÷ ${TRAVEL_TIME_REF_S}s reference` },
    { label: 'congestion', raw: rt.cost_congestion, unit: '', weight: wt('congestion', 0.6),
      contribution: Number(rt.cost_congestion || 0), note: 'already weighted' },
    { label: 'anomaly', raw: rt.cost_anomaly, unit: '', weight: wt('anomaly', 1.0),
      contribution: Number(rt.cost_anomaly || 0), note: 'already weighted' },
    { label: 'signal delay', raw: rt.cost_signal_delay_s, unit: 's',
      weight: wt('signal_delay', 0.4),
      contribution: wt('signal_delay', 0.4) * (Number(rt.cost_signal_delay_s || 0) / TRAVEL_TIME_REF_S),
      note: `÷ ${TRAVEL_TIME_REF_S}s reference` },
    { label: 'disruption', raw: rt.cost_disruption, unit: '', weight: wt('disruption', 0.5),
      contribution: Number(rt.cost_disruption || 0), note: 'already weighted' },
    { label: 'reliability', raw: rt.cost_reliability, unit: '', weight: wt('reliability', 0.3),
      contribution: Number(rt.cost_reliability || 0), note: 'already weighted' },
  ];
}

function routeExplain(r) {
  const rt = r.route;
  const terms = costTerms(rt);
  const max = Math.max(...terms.map((t) => Math.abs(t.contribution)), 0.0001);
  const sum = terms.reduce((a, t) => a + t.contribution, 0);
  const score = Number(rt.route_score || 0);
  const drift = score ? Math.abs(sum - score) / Math.abs(score) : 0;
  const alts = r.alternatives || [];
  return `
  <div class="card">
    <h4>Why this route <span class="chip ${rt.reliable ? 'ok' : 'warn'}">${rt.reliable ? 'reliable' : 'flagged unreliable'}</span></h4>
    <p class="sub">The planner minimised a six-term normalised cost. The weights in force are recorded with the route, so the choice is auditable rather than a black box.</p>
    <div class="tiles">
      <div class="tile"><em>eta</em><b>${num(rt.eta_s, 0)}<small> s</small></b></div>
      <div class="tile"><em>distance</em><b>${num(rt.total_distance_m)}<small> m</small></b></div>
      <div class="tile"><em>travel time</em><b>${num(rt.total_travel_time_s, 0)}<small> s</small></b></div>
      <div class="tile"><em>intersections</em><b>${num(rt.n_intersections)}</b><div class="sub2">${num((rt.signalised_intersections || []).length)} signalised</div></div>
      <div class="tile accent"><em>route score</em><b>${num(rt.route_score, 2)}</b><div class="sub2">lower is better</div></div>
      <div class="tile"><em>edges</em><b>${num((rt.edges || []).length)}</b></div>
    </div>
    <h4 class="mt">Cost breakdown <span class="chip dim">weighted contribution to the score</span></h4>
    <p class="sub" style="margin-bottom:8px">Travel time and signal delay come off the wire as raw seconds; the other four arrive already weighted and normalised. Everything below is converted to the same weighted, dimensionless scale the planner minimised, so the bars are actually comparable.</p>
    <div class="costbars">${terms.map((t) => `
      <div class="costbar"><span>${esc(t.label)}</span>
        <div class="track"><i style="width:${Math.min(100, (Math.abs(t.contribution) / max) * 100)}%"></i></div>
        <b>${num(t.contribution, 2)}</b></div>`).join('')}
    </div>
    <div class="tablewrap" style="margin-top:10px"><table class="tbl">
      <thead><tr><th>Term</th><th>As reported</th><th>Weight</th><th>Contribution</th><th>Share</th><th>Conversion</th></tr></thead>
      <tbody>${terms.map((t) => `<tr>
        <td>${esc(t.label)}</td>
        <td class="num">${num(t.raw, 2)}${esc(t.unit)}</td>
        <td class="num">${num(t.weight, 2)}</td>
        <td class="num">${num(t.contribution, 3)}</td>
        <td class="num">${sum ? num((t.contribution / sum) * 100, 1) : '—'}%</td>
        <td class="id">${esc(t.note)}</td></tr>`).join('')}
      </tbody></table></div>
    <p class="sub" style="margin-top:8px">Contributions sum to <b>${num(sum, 2)}</b>; the planner recorded a route score of <b>${num(score, 2)}</b>.
      ${drift > 0.02
      ? `<span style="color:var(--synth)"> They differ by ${num(drift * 100, 1)}% — the normalisation reference used here (${TRAVEL_TIME_REF_S}s, the config default) is not carried on the event, so it is an assumption rather than a reading.</span>`
      : ' They agree, so the conversion above matches what the planner did.'}</p>
    ${(rt.congested_segments || []).length ? `<p class="sub" style="margin-top:10px"><b>Congested segments on this route:</b> <span class="mono">${rt.congested_segments.map(esc).join(', ')}</span></p>` : ''}
    ${(rt.anomalous_segments_avoided || []).length ? `<p class="sub"><b>Anomalous segments avoided:</b> <span class="mono">${rt.anomalous_segments_avoided.map(esc).join(', ')}</span></p>` : ''}
    <p class="sub"><b>Path:</b> <span class="mono">${(rt.edges || []).map(esc).join(' → ')}</span></p>
    ${alts.length ? `<h4 class="mt">Alternatives considered</h4>
      <div class="tablewrap"><table class="tbl">
        <thead><tr><th>Rank</th><th>Score</th><th>ETA</th><th>Distance</th><th>Signals</th><th>Reliable</th></tr></thead>
        <tbody>${alts.map((a) => `<tr>
          <td class="num">${num(a.rank)}</td><td class="num">${num(a.route_score, 2)}</td>
          <td class="num">${num(a.eta_s, 0)}s</td><td class="num">${num(a.total_distance_m)}m</td>
          <td class="num">${num((a.signalised_intersections || []).length)}</td>
          <td>${a.reliable ? '<span class="chip ok">yes</span>' : '<span class="chip warn">no</span>'}</td>
        </tr>`).join('')}</tbody></table></div>` : ''}
  </div>`;
}

/* ── incidents ────────────────────────────────────────────────── */
export function renderIncidents() {
  const banner = document.getElementById('incident-banner');
  const host = document.getElementById('incident-list');
  if (!host) return;

  const detector = S.run?.incident_detector || '';
  if (banner) {
    banner.className = 'banner warn';
    banner.innerHTML = detector.startsWith('enabled')
      ? '<b>Detector active.</b> Candidates will appear here as the graph model crosses its conformal threshold.'
      : `<b>The detector is real code with nothing to detect.</b> ${esc(detector || 'No run yet.')} No trained model ships in this checkout, so M6 raises no candidates — that is the repo's own honest status, not a fault in this page. The gate below is live and will work the moment a candidate exists; to exercise the pipeline itself, run <code>m6_incident_injection_gate</code> from Gates.`;
  }

  if (!S.incidents.length) {
    host.innerHTML = `<p class="sub" style="margin:0">The registry is empty. It is in-memory in <code>api-service</code> and rebuilt from the bus on every restart.</p>`;
    return;
  }
  host.innerHTML = S.incidents.map((i) => {
    const state = i.state || i.status || 'UNKNOWN';
    const isCandidate = String(state).toUpperCase() === 'CANDIDATE';
    return `<div class="rowcard ${isCandidate ? 'on' : ''}">
      <div class="rc-head">
        <h5>${esc(i.intersection_id || '—')} · ${esc(i.link_id || '')}</h5>
        <div class="rc-meta">
          <span class="chip ${isCandidate ? 'warn' : 'ok'}">${esc(state)}</span>
          ${i.classification ? `<span class="chip">${esc(i.classification)}</span>` : ''}
        </div>
      </div>
      <div class="kvgrid">
        <div><i>fused probability</i>${num(i.fused_probability, 3)}</div>
        <div><i>threshold tau</i>${num(i.threshold_tau, 3)}</div>
        <div><i>graph score</i>${num(i.graph_score, 2)}</div>
        <div><i>vision score</i>${i.vision_score == null ? 'n/a (M8)' : num(i.vision_score, 2)}</div>
        <div><i>detector</i>${esc(i.detector_version || '—')}</div>
        <div><i>id</i>${esc(String(i.incident_id || '').slice(0, 8))}</div>
      </div>
      ${isCandidate ? `<div class="rc-btns">
        <select class="mono" id="cls-${esc(i.incident_id)}" style="background:var(--panel2);border:1px solid var(--line2);border-radius:7px;padding:6px 9px;color:var(--ink);font-size:12px">
          ${(S.boot?.incident_classes || ['unknown'])
        .map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}
        </select>
        <button class="btn ok sm" data-incident="${esc(i.incident_id)}" data-action="confirm">Confirm incident</button>
        <button class="btn ghost sm" data-incident="${esc(i.incident_id)}" data-action="reject">Reject as false alarm</button>
      </div>
      <p class="sub" style="margin:8px 0 0">A rejection is a confirmed-normal calibration point for the conformal threshold. Both actions need the API key and are recorded in the hash-chained audit trail.</p>` : ''}
    </div>`;
  }).join('');
}

/* ── kpis & runs ──────────────────────────────────────────────── */
export function renderKpis() {
  const tiles = document.getElementById('kpi-tiles');
  const table = document.getElementById('runs-table');
  if (!table) return;

  const scored = S.runs.filter((r) => r.metrics && !r.metrics.error);
  const last = scored[0];
  if (tiles) {
    tiles.innerHTML = last ? `
      <div class="tile"><em>last scored run</em><b style="font-size:14px">${esc(last.label || last.id)}</b><div class="sub2">${esc(last.config?.demand)} · ${esc(last.config?.controller)}</div></div>
      <div class="tile"><em>person delay</em><b>${num(last.metrics.person_delay_s)}</b></div>
      <div class="tile"><em>throughput</em><b>${num(last.metrics.person_throughput_per_hour)}<small>/h</small></b></div>
      <div class="tile"><em>mean wait</em><b>${num(last.metrics.wait_mean_s, 1)}<small>s</small></b></div>
      <div class="tile"><em>stops / veh</em><b>${num(last.metrics.stops_per_vehicle, 2)}</b></div>
      <div class="tile"><em>runs recorded</em><b>${num(S.runs.length)}</b><div class="sub2">${num(scored.length)} scored</div></div>`
      : `<div class="tile"><em>runs recorded</em><b>${num(S.runs.length)}</b><div class="sub2">none scored yet</div></div>`;
  }

  table.innerHTML = `<thead><tr>
      <th></th><th>Run</th><th>Traffic</th><th>Controller</th><th>State</th>
      <th>Person delay</th><th>Throughput</th><th>Mean wait</th><th>Stops</th><th>Arrivals</th><th></th>
    </tr></thead><tbody>${S.runs.length ? S.runs.map((r) => {
    const m = r.metrics || {};
    const od = r.od || {};
    return `<tr>
      <td><input type="checkbox" data-runsel="${esc(r.id)}" ${S.selected.has(r.id) ? 'checked' : ''}></td>
      <td><b>${esc(r.label || r.id)}</b><br><span class="id">${esc(r.id)}</span></td>
      <td>${esc(r.config?.demand || '—')}</td>
      <td>${esc(r.config?.controller || '—')}<br><span class="id">${esc(r.config?.engine || '')}${r.config?.seed != null ? ` · seed ${r.config.seed}` : ''}</span></td>
      <td><span class="chip ${{ finished: 'ok', failed: 'bad', running: 'cy', stopped: 'warn' }[r.state] || 'dim'}">${esc(r.state || '—')}</span>${r.error ? `<br><span class="id" style="color:#F0A3AB" title="${esc(r.error)}">${esc(r.error.length > 44 ? `${r.error.slice(0, 44)}…` : r.error)}</span>` : ''}</td>
      <td class="num">${num(m.person_delay_s)}</td>
      <td class="num">${num(m.person_throughput_per_hour)}</td>
      <td class="num">${num(m.wait_mean_s, 1)}</td>
      <td class="num">${num(m.stops_per_vehicle, 2)}</td>
      <td class="num">${od.target_arrivals ? `${num(od.arrived)}/${num(od.target_arrivals)}` : '—'}</td>
      <td><button class="btn ghost sm" data-delrun="${esc(r.id)}">del</button></td>
    </tr>`;
  }).join('') : '<tr><td class="empty" colspan="11">No runs yet.</td></tr>'}</tbody>`;

  const cmp = document.getElementById('btn-compare');
  if (cmp) cmp.disabled = S.selected.size < 2;
}

export function renderCompare(data) {
  const host = document.getElementById('compare-out');
  if (!host) return;
  if (!data) { host.innerHTML = ''; return; }
  const runs = data.runs || [];
  host.innerHTML = `
    <div class="card">
      <h4>Side by side</h4>
      <div class="tablewrap"><table class="cmp">
        <thead><tr><th>KPI</th>${runs.map((r) => `<th>${esc(r.label || r.id)}<br>
          <span class="mono" style="font-weight:400;text-transform:none;letter-spacing:0">${esc(r.config?.demand)} · ${esc(r.config?.controller)}${r.config?.seed != null ? ` · seed ${r.config.seed}` : ''}</span></th>`).join('')}
          ${runs.length === 2 ? '<th>Δ</th>' : ''}</tr></thead>
        <tbody>${(data.rows || []).map((row) => `<tr>
          <td>${esc(row.label)} <span class="mono" style="color:var(--faint)">${esc(row.unit)}</span></td>
          ${row.values.map((v) => `<td class="num ${row.best != null && v === row.best ? 'best' : ''}">${num(v, row.key === 'stops_per_vehicle' ? 2 : 1)}</td>`).join('')}
          ${runs.length === 2 ? `<td class="num delta ${deltaClass(row)}">${row.delta_pct == null ? '—' : `${row.delta_pct > 0 ? '+' : ''}${num(row.delta_pct, 1)}%`}</td>` : ''}
        </tr>`).join('')}</tbody>
      </table></div>
      <div class="banner warn" style="margin-top:12px"><b>Read this before quoting a number.</b> ${esc(data.caveat)}</div>
    </div>`;
}

function deltaClass(row) {
  if (row.delta_pct == null || row.delta_pct === 0) return '';
  const worse = row.lower_is_better ? row.delta_pct > 0 : row.delta_pct < 0;
  return worse ? 'up' : 'down';
}

/* ── milestones ───────────────────────────────────────────────── */
export function renderMilestones() {
  const host = document.getElementById('milestone-list');
  if (!host || !S.boot) return;
  const statusChip = {
    done: 'ok', 'done, verified': 'ok', partial: 'warn', superseded: 'dim',
    'built, model undertrained': 'warn', 'not started': 'dim',
  };
  host.innerHTML = S.boot.milestones.map((m) => {
    const v = S.verdicts[m.id];
    return `<div class="rowcard">
      <div class="rc-head">
        <h5><span class="mono" style="color:var(--cy)">${esc(m.id)}</span> ${esc(m.title)}</h5>
        <div class="rc-meta">
          <span class="chip ${statusChip[m.repo_status] || 'dim'}">repo: ${esc(m.repo_status)}</span>
          ${v ? `<span class="chip ${v === 'pass' ? 'ok' : v === 'fail' ? 'bad' : 'dim'}">you: ${esc(v)}</span>` : ''}
        </div>
      </div>
      <p class="claim">${esc(m.claim)}</p>
      <div class="howto"><b>How to test it here:</b> ${m.how.replace(/`([^`]+)`/g, (_, c) => `<code>${esc(c)}</code>`)}
        <br><b>You should see:</b> ${esc(m.verify)}</div>
      <div class="rc-btns">
        ${m.section ? `<button class="btn sm" data-go2="${esc(m.section)}">Open the screen</button>` : ''}
        <span class="hint">Your verdict:</span>
        <button class="btn ${v === 'pass' ? 'ok' : 'ghost'} sm" data-verdict="${esc(m.id)}:pass">Pass</button>
        <button class="btn ${v === 'fail' ? 'danger' : 'ghost'} sm" data-verdict="${esc(m.id)}:fail">Fail</button>
        <button class="btn ${v === 'skip' ? 'on' : 'ghost'} sm" data-verdict="${esc(m.id)}:skip">N/A</button>
      </div>
    </div>`;
  }).join('');
}

/* ── demos ────────────────────────────────────────────────────── */
export function renderDemos() {
  const host = document.getElementById('demo-list');
  if (!host || !S.boot) return;
  const busy = !!S.demo;
  host.innerHTML = S.boot.demos.map((d) => `
    <div class="rowcard">
      <div class="rc-head"><h5>${esc(d.title)}</h5>
        <div class="rc-meta"><span class="chip">${esc(d.duration)}</span>
        <span class="chip dim">${d.steps.length} steps</span></div></div>
      <p>${esc(d.summary)}</p>
      <div class="rc-btns">
        <button class="btn ${busy ? '' : 'primary'} sm" data-demo="${esc(d.id)}" ${busy ? 'disabled' : ''}>
          ${busy ? 'a demo is running' : 'Run this demo'}</button>
      </div>
    </div>`).join('');
}

export function renderDemoRunner() {
  const box = document.getElementById('demo-runner');
  if (!box) return;
  if (!S.demo) { box.hidden = true; return; }
  box.hidden = false;
  document.getElementById('demo-title').textContent = S.demo.def.title;
  const host = document.getElementById('demo-steps');
  host.innerHTML = S.demo.def.steps.map((st, i) => {
    const state = S.demo.states[i] || (i === S.demo.i ? 'now' : '');
    return `<div class="dstep ${state}">
      <span class="di">${state === 'done' ? '✓' : state === 'fail' ? '✕' : i + 1}</span>
      <span>${esc(describeStep(st))}${S.demo.notes[i] ? ` <span class="mono" style="opacity:.7">— ${esc(S.demo.notes[i])}</span>` : ''}</span>
    </div>`;
  }).join('');
  const now = host.querySelector('.dstep.now');
  if (now) now.scrollIntoView({ block: 'nearest' });
}

function describeStep(st) {
  switch (st.kind) {
    case 'note': return st.text;
    case 'ensure_stack': return 'Make sure the bus and api-service are up.';
    case 'start_run': return `Start a run: ${st.config.demand} traffic, ${st.config.controller}${st.config.od ? `, ${st.config.od.count} vehicles ${st.config.od.origin}→${st.config.od.destination}` : ''}.`;
    case 'goto': return `Switch to the ${st.section} screen.`;
    case 'wait_until': return st.text || `Wait for ${st.what.replace(/_/g, ' ')}.`;
    case 'anomaly': return `Inject ${st.payload.severity} ${st.payload.anomaly_type} on ${st.payload.edge_id}.`;
    case 'dispatch': return `Dispatch ${st.payload.vehicle_kind} from ${st.payload.source_edge} to ${st.payload.destination_edge}.`;
    case 'corridor': return 'Activate the green corridor on the newest route-ready request.';
    case 'compare_last': return `Compare the last ${st.n} runs.`;
    default: return st.kind;
  }
}

/* ── gates ────────────────────────────────────────────────────── */
export function renderGates() {
  const host = document.getElementById('gate-list');
  if (!host || !S.boot) return;
  const running = S.status?.stack?.gate;
  host.innerHTML = S.boot.gates.map((g) => {
    const isThis = running?.running && running.meta?.gate_id === g.id;
    return `<div class="rowcard ${isThis ? 'on' : ''}">
      <div class="rc-head"><h5>${esc(g.title)}</h5>
        <div class="rc-meta">
          <span class="chip ${g.heavy ? 'warn' : 'dim'}">${esc(g.runtime)}</span>
          <span class="chip dim mono">${esc(g.script)}</span>
          ${g.present ? '' : '<span class="chip bad">not in this checkout</span>'}
        </div></div>
      <p>${esc(g.blurb)}</p>
      <div class="rc-btns">
        ${isThis
        ? `<button class="btn danger sm" data-gate-stop="1">Stop this script</button>
           <span class="hint">running · pid ${running.pid} · ${dur(running.uptime_s)}</span>`
        : `<button class="btn sm" data-gate="${esc(g.id)}" ${!g.present || running?.running ? 'disabled' : ''}>Run script</button>`}
      </div>
    </div>`;
  }).join('');
}

export function renderResults(index) {
  const host = document.getElementById('results-list');
  if (!host) return;
  if (!index?.files?.length) {
    host.innerHTML = `<p class="sub" style="margin:0">No JSON under <code>scripts/results/</code> yet.</p>`;
    return;
  }
  host.innerHTML = `<p class="sub">Every gate script writes its output here and the repo treats these as never-hand-edited. Read-only from this page.</p>
    <div class="tablewrap"><table class="tbl"><thead><tr><th>File</th><th>Size</th><th>Written</th><th></th></tr></thead>
    <tbody>${index.files.slice(0, 60).map((f) => `<tr>
      <td class="id">${esc(f.name)}</td>
      <td class="num">${num(f.size / 1024, 1)} kB</td>
      <td>${esc(ago(f.mtime))}</td>
      <td><button class="btn ghost sm" data-result="${esc(f.name)}">View</button></td>
    </tr>`).join('')}</tbody></table></div>`;
}

export function renderResultView(res) {
  const host = document.getElementById('result-view');
  if (!host) return;
  if (!res?.ok) { host.innerHTML = res ? `<div class="banner bad">${esc(res.reason)}</div>` : ''; return; }
  host.innerHTML = `<div class="card"><h4>${esc(res.name)}</h4>
    <pre class="logbox" style="max-height:460px">${esc(JSON.stringify(res.content, null, 2))}</pre></div>`;
}

/* ── settings ─────────────────────────────────────────────────── */
export function renderSettings() {
  const table = document.getElementById('env-table');
  const hint = document.getElementById('key-hint');
  if (!table || !S.boot) return;
  const r = S.boot.repo;
  const c = S.boot.config;
  const rows = [
    ['CAPSTONE folder', r.capstone_dir],
    ['Repo (read-only)', r.repo + (r.repo_found ? '' : '  — NOT FOUND')],
    ['This site', c.site_dir],
    ['Generated artefacts', c.var_dir],
    ['SUMO network', r.network_found ? 'found' : 'MISSING'],
    ['Repo virtualenv', r.venv_python || r.venv_problem || 'MISSING — run make setup'],
    ['SUMO binary', r.sumo_binary || 'not found'],
    ['Docker', r.docker || 'not installed'],
    ['redis-server on PATH', r.redis_server || 'no'],
    ['Redis URL', c.redis_url],
    ['api-service port', String(c.api_port)],
    ['WebSocket', `ws://${location.hostname}:${c.api_port}/v1/stream`],
    ['Corridor', `${S.boot.network.counts.edges} edges · ${S.boot.network.counts.junctions} junctions · ${S.boot.network.counts.traffic_lights} traffic lights`],
    ['Facilities', `${S.boot.facilities.length} hospitals/clinics from OSM`],
  ];
  table.innerHTML = `<tbody>${rows.map(([k, v]) =>
    `<tr><td style="width:40%">${esc(k)}</td><td class="id">${esc(v)}</td></tr>`).join('')}</tbody>`;
  if (hint) {
    hint.textContent = {
      generated: 'This tool generated a key, saved it under var/, and passes it to api-service when it starts it. Nothing to do.',
      saved: 'Reusing the key saved under var/ — the same one across restarts of this tool.',
      env: 'Using the ITMS_API_KEY from your environment.',
      pasted: 'Using the key you pasted.',
    }[c.api_key_source] || '';
  }
}

/* ── selectors ────────────────────────────────────────────────── */
export function populateSelectors() {
  if (!S.boot) return;
  const net = S.boot.network;
  const opts = (ids, selected) => ids.map((id) =>
    `<option value="${esc(id)}" ${id === selected ? 'selected' : ''}>${esc(edgeLabel(id))}</option>`).join('');

  const sug = S.boot.suggested || {};
  const sources = net.edge_order.filter((id) => net.edges[id].fringe_source);
  const sinks = net.edge_order.filter((id) => net.edges[id].fringe_sink);
  const groupOpts = (primary, primaryLabel, selected) => `
    <optgroup label="${primaryLabel}">${opts(primary, selected)}</optgroup>
    <optgroup label="Every road on the corridor">${opts(net.edge_order, selected)}</optgroup>`;

  const set = (id, html) => { const el = document.getElementById(id); if (el && !el.dataset.filled) { el.innerHTML = html; el.dataset.filled = '1'; } };
  set('od-origin', groupOpts(sources, 'Corridor entry points', sug.origin));
  set('od-dest', groupOpts(sinks, 'Corridor exit points', sug.destination));
  set('an-edge', opts(net.edge_order, sug.mid_edge));
  set('ev-src', groupOpts(sources, 'Corridor entry points', sug.origin));
  set('ev-dst', groupOpts(sinks, 'Corridor exit points', sug.destination));

  set('an-type', S.boot.anomaly_types.map((t, i) =>
    `<option value="${esc(t)}" ${i === 2 ? 'selected' : ''}>${esc(t.replace(/_/g, ' ').toLowerCase())}</option>`).join(''));
  set('an-sev', S.boot.anomaly_severities.map((s, i) =>
    `<option value="${esc(s.id)}" ${i === 2 ? 'selected' : ''}>${esc(s.label)}</option>`).join(''));
  set('ev-kind', S.boot.vehicle_kinds.map((k) =>
    `<option value="${esc(k)}">${esc(k.replace(/_/g, ' ').toLowerCase())}</option>`).join(''));
  set('ev-facility', '<option value="">— pick a road above instead —</option>'
    + S.boot.facilities.filter((f) => f.edge).map((f) =>
      `<option value="${esc(f.edge)}">${esc(f.name)} (${esc(f.kind)})</option>`).join(''));
  renderSeverityNote();
}

export function renderSeverityNote() {
  const host = document.getElementById('an-note');
  const sel = document.getElementById('an-sev');
  if (!host || !sel || !S.boot) return;
  const s = S.boot.anomaly_severities.find((x) => x.id === sel.value);
  host.innerHTML = s
    ? `<b>${esc(s.label)}:</b> ${esc(s.note)}.`
    : '';
}
