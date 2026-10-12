/* The live corridor map.

   Vector-only by default: the network is drawn from the repo's own exported
   GeoJSON, so the map works with no internet and no tile server. OSM tiles are
   an opt-in toggle for when you want the real streets underneath.

   Roads are coloured by how loaded they are, which is the one thing you want to
   see at a glance; everything else (queues, phases, anomaly severity) is in the
   tooltip or the panels. */

import { S, markDirty, esc, num } from './state.js';

const VTYPE_COLOR = {
  veh_motorcycle: '#57C97B', od_motorcycle: '#57C97B',
  veh_car: '#7FD1FF', od_car: '#7FD1FF',
  veh_auto: '#E8B23A', od_auto: '#E8B23A',
  veh_bus: '#E2703A', od_bus: '#E2703A',
};
const SEVERITY_COLOR = { low: '#E8B23A', medium: '#E2703A', high: '#E05A6B', blocked: '#FF3355' };

// CARTO started requiring a (free) API key for their basemap tiles -- without
// one every tile just shows an "API KEY REQUIRED" watermark instead of the
// street map. This key is a public map-tile key (meant to sit in a browser
// URL, not a secret), issued free at https://carto.com/basemaps/apikey/.
const CARTO_KEY = 'cb1_3jf3_1_eebdaa5dfe6a7e754d932826';
const CARTO_ATTRIBUTION = '&copy; <a href="https://carto.com/attributions">CARTO</a>, '
  + '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

let map = null;
let tileLayer = null;
let tileAttribution = null;
const L_ = () => window.L;
const groups = {};
const roadLines = new Map();   // edge_id -> polyline
const vehicleDots = new Map(); // vehicle_id -> circleMarker
const tlsDots = new Map();     // tls_id -> circleMarker
let routeLine = null;
let evMarkers = new Map();
let lastDraw = 0;

export function initMap() {
  if (map || !L_() || !S.boot) return;
  const net = S.boot.network;
  map = L_().map('leaf', {
    preferCanvas: true,
    // The layer toggles live along the top edge, so the zoom control goes to
    // the opposite corner rather than sitting on top of them.
    zoomControl: false,
    attributionControl: false,
    center: net.center,
    zoom: 14,
  });
  L_().control.zoom({ position: 'bottomright' }).addTo(map);
  ['roads', 'anomaly', 'facilities', 'junctions', 'route', 'corridor', 'vehicles', 'ev']
    .forEach((k) => { groups[k] = L_().layerGroup().addTo(map); });

  drawRoads();
  drawJunctions();
  drawFacilities();
  if (S.layers.tiles) toggleTiles();
  try { map.fitBounds(net.bounds, { padding: [40, 40] }); } catch { /* degenerate bounds */ }
  renderLegend();
  renderTools();
}

/* ── static geometry ──────────────────────────────────────────── */
function drawRoads() {
  const edges = S.boot.network.edges;
  groups.roads.clearLayers();
  roadLines.clear();
  for (const [id, e] of Object.entries(edges)) {
    if (!e.coords || e.coords.length < 2) continue;
    const latlngs = e.coords.map(([lon, lat]) => [lat, lon]);
    const line = L_().polyline(latlngs, {
      color: '#2E383C',
      weight: Math.min(9, 3 + (e.num_lanes || 1) * 1.6),
      opacity: 0.95,
      lineCap: 'round',
      interactive: true,
    });
    line.on('click', () => onRoadClick(id));
    line.bindTooltip(() => roadTooltip(id), { sticky: true, direction: 'top' });
    line.addTo(groups.roads);
    roadLines.set(id, line);
  }
}

function drawJunctions() {
  groups.junctions.clearLayers();
  tlsDots.clear();
  const { junctions } = S.boot.network;
  for (const j of Object.values(junctions)) {
    if (j.lat == null || j.lon == null) continue;
    if (j.is_traffic_light) {
      const dot = L_().circleMarker([j.lat, j.lon], {
        radius: 6, color: '#5B686D', weight: 2, fillColor: '#12171A', fillOpacity: 1,
      });
      dot.bindTooltip(() => tlsTooltip(j.id), { direction: 'top' });
      dot.addTo(groups.junctions);
      tlsDots.set(j.id, dot);
    } else {
      L_().circleMarker([j.lat, j.lon], {
        radius: 2, color: '#2E383C', weight: 1, fillOpacity: 0.6, interactive: false,
      }).addTo(groups.junctions);
    }
  }
}

function drawFacilities() {
  groups.facilities.clearLayers();
  for (const f of S.boot.facilities || []) {
    if (f.lat == null) continue;
    L_().circleMarker([f.lat, f.lon], {
      radius: f.kind === 'hospital' ? 4 : 3,
      color: f.kind === 'hospital' ? '#A98BFF' : '#5B686D',
      weight: 1.5, fillColor: '#12171A', fillOpacity: 0.9,
    })
      .bindTooltip(`${esc(f.name)}<br><span class="mono">${esc(f.kind)} · edge ${esc(f.edge)}</span>`,
        { direction: 'top' })
      .addTo(groups.facilities);
  }
  if (!S.layers.facilities) map.removeLayer(groups.facilities);
}

/* ── per-frame update ─────────────────────────────────────────── */
export function drawMap(force = false) {
  if (!map) return;
  const now = performance.now();
  if (!force && now - lastDraw < 160) return;
  lastDraw = now;
  paintRoads();
  paintSignals();
  paintVehicles();
  paintEmergency();
  paintAnomalies();
}

function loadOf(edgeId) {
  // The runner's own per-edge sample is authoritative when a test-lab run is
  // going; the ApproachState stream covers the repo-entrypoint engines too.
  const fromRun = S.run?.network?.edges?.[edgeId];
  if (fromRun) return { occ: fromRun.occ ?? 0, n: fromRun.n ?? 0, halting: fromRun.halting ?? 0, speed: fromRun.speed };
  const a = S.approach.get(edgeId);
  if (a) return { occ: a.occupancy ?? 0, n: Math.round(a.q_pcu ?? 0), halting: null, speed: null };
  return null;
}

function paintRoads() {
  for (const [id, line] of roadLines) {
    const anomaly = activeAnomalyOn(id);
    if (anomaly) {
      line.setStyle({ color: SEVERITY_COLOR[String(anomaly.severity).toLowerCase()] || '#E05A6B', opacity: 1 });
      continue;
    }
    const load = loadOf(id);
    if (!load) { line.setStyle({ color: '#2E383C', opacity: 0.95 }); continue; }
    const occ = Math.min(1, load.occ * 4); // occupancy rarely exceeds ~0.25 free-flowing
    line.setStyle({ color: rampColor(occ), opacity: 0.95 });
  }
}

function rampColor(t) {
  // grey → cyan → amber → red: unloaded, flowing, loaded, jammed
  const stops = [[0, [46, 56, 60]], [0.18, [63, 224, 255]], [0.55, [232, 178, 58]], [1, [224, 90, 107]]];
  for (let i = 1; i < stops.length; i += 1) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1]; const [t1, c1] = stops[i];
      const f = (t - t0) / (t1 - t0 || 1);
      return `rgb(${c0.map((c, k) => Math.round(c + (c1[k] - c) * f)).join(',')})`;
    }
  }
  return 'rgb(224,90,107)';
}

function paintSignals() {
  for (const [id, dot] of tlsDots) {
    const s = S.signals.get(id);
    if (!s) { dot.setStyle({ color: '#5B686D', fillColor: '#12171A', radius: 6 }); continue; }
    if (s.faulted) { dot.setStyle({ color: '#E05A6B', fillColor: '#3A1212', radius: 7 }); continue; }
    const preempt = s.source === 'corridor_preemption';
    dot.setStyle({
      color: preempt ? '#57C97B' : '#3FE0FF',
      fillColor: preempt ? '#153A31' : '#0E3A45',
      radius: preempt ? 8 : 6,
      weight: preempt ? 3 : 2,
    });
  }
}

function paintVehicles() {
  if (!S.layers.vehicles) { groups.vehicles.clearLayers(); vehicleDots.clear(); return; }
  const seen = new Set();
  for (const [id, v] of S.vehicles) {
    if (v.lat == null) continue;
    seen.add(id);
    let dot = vehicleDots.get(id);
    const color = VTYPE_COLOR[v.type] || '#9BAAB0';
    if (!dot) {
      dot = L_().circleMarker([v.lat, v.lon], {
        radius: v.type === 'veh_bus' || v.type === 'od_bus' ? 4.2 : 3,
        color, weight: 0, fillColor: color, fillOpacity: 0.9, interactive: false,
      }).addTo(groups.vehicles);
      vehicleDots.set(id, dot);
    } else {
      dot.setLatLng([v.lat, v.lon]);
      // stopped vehicles fade; it makes standing queues visible at a glance
      dot.setStyle({ fillOpacity: v.speed < 0.4 ? 0.42 : 0.9 });
    }
  }
  for (const [id, dot] of vehicleDots) {
    if (!seen.has(id)) { groups.vehicles.removeLayer(dot); vehicleDots.delete(id); }
  }
}

function paintAnomalies() {
  groups.anomaly.clearLayers();
  if (!S.layers.anomalies) return;
  for (const a of S.anomalies.values()) {
    if (a.status !== 'ACTIVE') continue;
    const e = S.boot.network.edges[a.edge_id];
    if (!e || e.lat == null) continue;
    const color = SEVERITY_COLOR[String(a.severity).toLowerCase()] || '#E05A6B';
    L_().circleMarker([e.lat, e.lon], {
      radius: 9, color, weight: 2.5, fillColor: color, fillOpacity: 0.22,
    })
      .bindTooltip(
        `<b>${esc(a.anomaly_type)}</b> · ${esc(a.severity)}<br>` +
        `<span class="mono">${esc(a.edge_id)} · impact ${num(a.estimated_impact, 2)} · ${esc(a.source)}</span>`,
        { direction: 'top' })
      .addTo(groups.anomaly);
  }
}

function paintEmergency() {
  groups.route.clearLayers();
  groups.corridor.clearLayers();
  groups.ev.clearLayers();
  evMarkers = new Map();
  routeLine = null;
  if (!S.layers.emergency) return;

  const edges = S.boot.network.edges;
  for (const r of S.requests.values()) {
    if (!r.route || ['COMPLETED', 'CANCELLED'].includes(r.state)) continue;
    const pts = [];
    for (const eid of r.route.edges || []) {
      const e = edges[eid];
      if (e?.coords) e.coords.forEach(([lon, lat]) => pts.push([lat, lon]));
    }
    if (pts.length > 1) {
      routeLine = L_().polyline(pts, {
        color: '#3FE0FF', weight: 4, opacity: 0.85, dashArray: '9 7', interactive: false,
      }).addTo(groups.route);
    }
  }

  for (const c of S.corridors.values()) {
    if (!['ACTIVE', 'PROPOSED'].includes(c.status)) continue;
    for (const res of c.reservations || []) {
      const j = S.boot.network.junctions[res.intersection_id];
      if (!j || j.lat == null) continue;
      L_().circleMarker([j.lat, j.lon], {
        radius: 13, color: '#57C97B', weight: 2, fillOpacity: 0.08, interactive: false,
      }).addTo(groups.corridor);
    }
  }

  for (const [vid, ev] of S.evs) {
    if (ev.lat == null || ev.status === 'ARRIVED') continue;
    const m = L_().circleMarker([ev.lat, ev.lon], {
      radius: 7, color: '#fff', weight: 2, fillColor: '#E05A6B', fillOpacity: 1,
    })
      .bindTooltip(
        `<b>${esc(vid)}</b> · ${esc(ev.status)}<br>` +
        `<span class="mono">${num((ev.route_progress || 0) * 100, 0)}% · ${num(ev.speed_mps, 1)} m/s` +
        `${ev.eta_s ? ` · eta ${num(ev.eta_s, 0)}s` : ''}</span>`,
        { direction: 'top', permanent: false })
      .addTo(groups.ev);
    evMarkers.set(vid, m);
  }
}

/* ── tooltips ─────────────────────────────────────────────────── */
function roadTooltip(id) {
  const e = S.boot.network.edges[id];
  const load = loadOf(id);
  const a = activeAnomalyOn(id);
  const lines = [
    `<b>${esc(e.name || 'unnamed road')}</b>`,
    `<span class="mono">${esc(id)} · ${num(e.length_m)} m · ${e.num_lanes} lane(s) · ${num(e.speed_limit_mps, 1)} m/s</span>`,
  ];
  if (load) {
    lines.push(`<span class="mono">${load.n} veh · occ ${num(load.occ * 100, 1)}%` +
      (load.halting != null ? ` · ${load.halting} halted` : '') +
      (load.speed != null ? ` · ${num(load.speed, 1)} m/s` : '') + '</span>');
  }
  if (e.signalised_entry_tls?.length) {
    lines.push(`<span class="mono">signalised entry: ${esc(e.signalised_entry_tls.join(', '))}</span>`);
  }
  if (a) lines.push(`<span class="mono" style="color:#F0A3AB">${esc(a.anomaly_type)} · ${esc(a.severity)}</span>`);
  if (S.pick) lines.push(`<b style="color:#3FE0FF">click to set ${esc(S.pick.label)}</b>`);
  return lines.join('<br>');
}

function tlsTooltip(id) {
  const s = S.signals.get(id);
  const tl = S.boot.network.traffic_lights[id] || {};
  const rows = [`<b>${esc(id)}</b>`,
    `<span class="mono">${tl.n_phases || '?'} phases · ${tl.n_links || '?'} links</span>`];
  if (s) {
    rows.push(`<span class="mono">phase ${esc(s.phase)} · ${esc(s.source)}</span>`);
    rows.push(`<span class="mono">${s.changes} commanded change(s)</span>`);
    if (s.faulted) rows.push(`<span class="mono" style="color:#F0A3AB">${esc(s.faulted)}</span>`);
  } else {
    rows.push('<span class="mono">no commanded phase yet</span>');
  }
  return rows.join('<br>');
}

function activeAnomalyOn(edgeId) {
  for (const a of S.anomalies.values()) {
    if (a.status === 'ACTIVE' && a.edge_id === edgeId) return a;
  }
  return null;
}

/* ── picking ──────────────────────────────────────────────────── */
function onRoadClick(edgeId) {
  if (!S.pick) return;
  const el = document.getElementById(S.pick.target);
  if (el) { el.value = edgeId; el.dispatchEvent(new Event('change', { bubbles: true })); }
  const label = S.pick.label;
  S.pick = null;
  markDirty('pick');
  window.dispatchEvent(new CustomEvent('itms-picked', { detail: { edgeId, label } }));
}

/* ── chrome ───────────────────────────────────────────────────── */
function renderTools() {
  const host = document.getElementById('maptools');
  if (!host) return;
  const defs = [
    ['vehicles', 'Vehicles'], ['signals', 'Signals'], ['anomalies', 'Anomalies'],
    ['emergency', 'Emergency'], ['facilities', 'Hospitals'], ['tiles', 'Street tiles'],
  ];
  host.innerHTML = defs.map(([k, label]) =>
    `<button class="mtool ${S.layers[k] ? 'on' : ''}" data-layer="${k}">${label}</button>`).join('')
    + '<button class="mtool" data-layer="fit">Fit corridor</button>';
  host.onclick = (ev) => {
    const key = ev.target?.dataset?.layer;
    if (!key) return;
    if (key === 'fit') { try { map.fitBounds(S.boot.network.bounds, { padding: [40, 40] }); } catch { /* */ } return; }
    S.layers[key] = !S.layers[key];
    if (key === 'tiles') toggleTiles();
    if (key === 'facilities') {
      if (S.layers.facilities) groups.facilities.addTo(map); else map.removeLayer(groups.facilities);
    }
    if (key === 'signals') {
      if (S.layers.signals) groups.junctions.addTo(map); else map.removeLayer(groups.junctions);
    }
    renderTools();
    drawMap(true);
  };
}

function toggleTiles() {
  if (S.layers.tiles) {
    if (!tileLayer) {
      // "voyager" is CARTO's light, muted-color street style (roads, parks,
      // water all rendered close to how Apple/Google Maps look) -- swapped
      // in from the plain dark basemap at the user's request. Opacity is
      // near-full since, unlike the dark tile, this one isn't meant to be
      // dimmed under the vector overlay.
      // CARTO's docs give voyager its own URL shape (no subdomain letters,
      // no retina suffix) -- different from the older dark_all/light_all
      // path. Using the wrong shape 404s every tile silently: no watermark,
      // just a blank map, which is what happened on the first attempt here.
      tileLayer = L_().tileLayer(
        `https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${CARTO_KEY}`,
        { maxZoom: 19, opacity: 0.92, attribution: CARTO_ATTRIBUTION },
      );
    }
    tileLayer.addTo(map);
    tileLayer.bringToBack();
    // CARTO's free tier requires crediting CARTO + OpenStreetMap on the map;
    // the app otherwise runs with no attribution control at all (see
    // initMap), so add a small one only while the basemap is actually shown.
    if (!tileAttribution) tileAttribution = L_().control.attribution({ position: 'bottomleft', prefix: false });
    tileAttribution.addTo(map);
  } else if (tileLayer) {
    map.removeLayer(tileLayer);
    if (tileAttribution) map.removeControl(tileAttribution);
  }
}

function renderLegend() {
  const host = document.getElementById('maplegend');
  if (!host) return;
  host.innerHTML = `
    <b>Road load</b>
    <div><i style="background:#2E383C"></i>empty</div>
    <div><i style="background:#3FE0FF"></i>flowing</div>
    <div><i style="background:#E8B23A"></i>loaded</div>
    <div><i style="background:#E05A6B"></i>jammed / anomaly</div>
    <b style="margin-top:8px">Vehicles</b>
    <div><i style="background:#7FD1FF"></i>car</div>
    <div><i style="background:#57C97B"></i>motorcycle</div>
    <div><i style="background:#E8B23A"></i>auto</div>
    <div><i style="background:#E2703A"></i>bus</div>
    <b style="margin-top:8px">Signals</b>
    <div><i style="background:#0E3A45;box-shadow:0 0 0 1.5px #3FE0FF"></i>controller</div>
    <div><i style="background:#153A31;box-shadow:0 0 0 2px #57C97B"></i>preemption</div>
    <div><i style="background:#3A1212;box-shadow:0 0 0 1.5px #E05A6B"></i>faulted</div>`;
}

export function mapReady() { return !!map; }
export function invalidateMapSize() { if (map) setTimeout(() => map.invalidateSize(), 60); }
export function flyToEdge(edgeId) {
  const e = S.boot?.network?.edges?.[edgeId];
  if (map && e?.lat != null) map.setView([e.lat, e.lon], 16, { animate: true });
}
