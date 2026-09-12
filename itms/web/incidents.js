/**
 * M6 Incident Detection UI Module.
 *
 * Listens for IncidentCandidate events from the WebSocket, displays
 * incident cards in a sidebar panel with Confirm / Reject buttons,
 * and places pulsing red markers on the Leaflet map.
 */

/* global L */

const IncidentUI = (() => {
  let _map = null;
  const _markers = {};   // candidateId → L.circleMarker
  const _cards = {};      // candidateId → DOM element
  const API_BASE = '/v1/incidents';

  // ---- approximate edge → lat/lng lookup (fallback: Vijayawada centre) ----
  const VJA_CENTER = [16.5062, 80.6480];

  function _estimatePosition(linkId) {
    // Use map centre with small random offset so markers don't stack.
    // In production this would look up edge geometry from PostGIS.
    const jitter = () => (Math.random() - 0.5) * 0.005;
    return [VJA_CENTER[0] + jitter(), VJA_CENTER[1] + jitter()];
  }

  // ---- public API ----

  function init(map) {
    _map = map;
    const panel = document.getElementById('incidents-panel');
    if (!panel) {
      console.warn('incidents-panel element not found');
    }
  }

  function handleCandidate(payload) {
    const cid = payload.candidate_id;
    if (_cards[cid]) return;  // duplicate

    // Map marker
    const pos = _estimatePosition(payload.link_id);
    const marker = L.circleMarker(pos, {
      radius: 12,
      color: '#ff0000',
      fillColor: '#ff4444',
      fillOpacity: 0.7,
      weight: 3,
      className: 'incident-pulse',
    }).addTo(_map);
    marker.bindTooltip(
      `Incident candidate on ${payload.link_id}<br>` +
      `Score: ${payload.fused_score?.toFixed(3) ?? '?'}`
    );
    _markers[cid] = marker;

    // Card
    const panel = document.getElementById('incidents-panel');
    const card = document.createElement('div');
    card.className = 'incident-card';
    card.id = `incident-card-${cid}`;
    card.innerHTML = `
      <h4>⚠ Incident Candidate</h4>
      <table>
        <tr><td>Link</td><td><b>${payload.link_id}</b></td></tr>
        <tr><td>Graph score</td><td>${payload.graph_score?.toFixed(3) ?? '—'}</td></tr>
        <tr><td>Fused score</td><td>${payload.fused_score?.toFixed(3) ?? '—'}</td></tr>
        <tr><td>Threshold (τ)</td><td>${payload.threshold?.toFixed(3) ?? '—'}</td></tr>
        <tr><td>Phase</td><td>${payload.signal_phase ?? '—'}</td></tr>
      </table>
      <div class="incident-actions">
        <button class="btn-confirm" onclick="IncidentUI.confirm('${cid}')">✓ Confirm</button>
        <button class="btn-reject"  onclick="IncidentUI.reject('${cid}')">✗ Reject</button>
      </div>
    `;
    panel.prepend(card);
    _cards[cid] = card;
  }

  async function confirm(cid) {
    try {
      const res = await fetch(`${API_BASE}/${cid}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed_by: 'operator', severity: 'unknown' }),
      });
      if (res.ok) _remove(cid, 'confirmed');
    } catch (e) { console.error('confirm failed', e); }
  }

  async function reject(cid) {
    try {
      const res = await fetch(`${API_BASE}/${cid}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: null }),
      });
      if (res.ok) _remove(cid, 'rejected');
    } catch (e) { console.error('reject failed', e); }
  }

  function _remove(cid, status) {
    if (_markers[cid]) { _map.removeLayer(_markers[cid]); delete _markers[cid]; }
    if (_cards[cid]) {
      _cards[cid].classList.add(`incident-${status}`);
      setTimeout(() => { _cards[cid]?.remove(); delete _cards[cid]; }, 1200);
    }
  }

  return { init, handleCandidate, confirm, reject };
})();
