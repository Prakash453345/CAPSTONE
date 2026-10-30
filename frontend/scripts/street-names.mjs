/**
 * Street names for the console's road networks, from OpenStreetMap (ODbL).
 *
 * The SUMO networks carry few or no street names (Amaravati's carries none),
 * so without this the console calls a road by its class: "Primary road to
 * Primary road". This reads the same OpenMapTiles vector tiles the basemap
 * draws and writes src/data/street-names.json with, for each road segment:
 *
 *   n  the street it runs along, when one named way follows it closely
 *      (most samples along the segment within 20 m and within 35° of it)
 *   a  the nearest village or neighbourhood, for "Unnamed road, Rayapudi"
 *
 * Segments without a confident match get no `n`; they are never guessed.
 *
 * Run from frontend/:  node scripts/street-names.mjs
 * (needs network access to tiles.openfreemap.org; pbf and
 * @mapbox/vector-tile come with maplibre-gl)
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import Pbf from "pbf";
import { VectorTile } from "@mapbox/vector-tile";

const NETWORKS = {
  vijayawada: [
    "../backend/data/scenarios/networks/vijayawada/vijayawada_corridor.geojson",
    "../backend/data/scenarios/networks/vijayawada/vijayawada_district.geojson",
  ],
  amaravati: ["../backend/data/scenarios/generated/amaravati_v2/amaravati_v2.geojson"],
};
const OUT = "src/data/street-names.json";
const Z = 14;
const MATCH_M = 20;
const MATCH_DEG = 35;
const AREA_M = 3000;
const AREA_CLASSES = new Set(["town", "village", "suburb", "neighbourhood", "hamlet", "quarter"]);

const cache = join(tmpdir(), "traffix-street-tiles");
mkdirSync(cache, { recursive: true });

async function tileTemplate() {
  const style = await (await fetch("https://tiles.openfreemap.org/styles/liberty")).json();
  const tilejson = await (await fetch(style.sources.openmaptiles.url)).json();
  return tilejson.tiles[0];
}

const lon2x = (lon) => Math.floor(((lon + 180) / 360) * 2 ** Z);
const lat2y = (lat) =>
  Math.floor(((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * 2 ** Z);

/** OSM spells some names in all capitals or all lower case; show them as
 *  words. A chain of several names ("A - B - C Road") keeps its last one. */
function tidy(name) {
  const parts = name.split(" - ");
  const s = (parts.length > 2 ? parts[parts.length - 1] : name).replace(/\s+/g, " ").trim();
  if (s !== s.toUpperCase() && s !== s.toLowerCase()) return s;
  if (/^[A-Z]{1,3}\d+[A-Z]?$/.test(s)) return s; // "E8", "NH16"
  return s.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase());
}

async function readTiles(template, [s, w, n, e]) {
  const places = new Map();
  const roads = [];
  for (let x = lon2x(w); x <= lon2x(e); x++) {
    for (let y = lat2y(n); y <= lat2y(s); y++) {
      const file = join(cache, `${Z}_${x}_${y}.pbf`);
      if (!existsSync(file)) {
        const res = await fetch(template.replace("{z}", Z).replace("{x}", x).replace("{y}", y));
        if (!res.ok) throw new Error(`tile ${x}/${y}: HTTP ${res.status}`);
        writeFileSync(file, Buffer.from(await res.arrayBuffer()));
      }
      const tile = new VectorTile(new Pbf(readFileSync(file)));
      const place = tile.layers.place;
      for (let i = 0; place && i < place.length; i++) {
        const f = place.feature(i);
        const name = f.properties["name:en"] || f.properties["name:latin"] || f.properties.name;
        if (!name || !AREA_CLASSES.has(f.properties.class)) continue;
        const [lng, lat] = f.toGeoJSON(x, y, Z).geometry.coordinates;
        places.set(name, { name: tidy(name), lng, lat });
      }
      const tn = tile.layers.transportation_name;
      for (let i = 0; tn && i < tn.length; i++) {
        const f = tn.feature(i);
        const name = f.properties["name:en"] || f.properties["name:latin"] || f.properties.name;
        if (!name) continue;
        const g = f.toGeoJSON(x, y, Z).geometry;
        const lines = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
        for (const coords of lines) roads.push({ name: tidy(name), coords });
      }
    }
  }
  return { places: [...places.values()], roads };
}

function bounds(features) {
  const b = [90, 180, -90, -180];
  for (const f of features) {
    const cs = f.geometry.type === "Point" ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const [lng, lat] of cs) {
      b[0] = Math.min(b[0], lat);
      b[1] = Math.min(b[1], lng);
      b[2] = Math.max(b[2], lat);
      b[3] = Math.max(b[3], lng);
    }
  }
  const pad = 0.01;
  return [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad];
}

function main(features, { places, roads }) {
  // A flat local projection in metres is plenty at city scale.
  const lat0 = features[0].geometry.coordinates[0][1] ?? features[0].geometry.coordinates[1];
  const kx = 111320 * Math.cos((lat0 * Math.PI) / 180);
  const ky = 110540;
  const P = ([lng, lat]) => [lng * kx, lat * ky];

  const segs = [];
  for (const r of roads) {
    for (let i = 1; i < r.coords.length; i++) segs.push({ name: r.name, a: P(r.coords[i - 1]), b: P(r.coords[i]) });
  }
  const CELL = 100;
  const grid = new Map();
  const key = (cx, cy) => `${cx},${cy}`;
  for (const s of segs) {
    const [x0, x1] = [Math.min(s.a[0], s.b[0]), Math.max(s.a[0], s.b[0])];
    const [y0, y1] = [Math.min(s.a[1], s.b[1]), Math.max(s.a[1], s.b[1])];
    for (let cx = Math.floor(x0 / CELL); cx <= Math.floor(x1 / CELL); cx++) {
      for (let cy = Math.floor(y0 / CELL); cy <= Math.floor(y1 / CELL); cy++) {
        const k = key(cx, cy);
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(s);
      }
    }
  }
  const bearing = (a, b) => (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
  const angleGap = (p, q) => {
    const d = Math.abs(((p - q) % 180) + 180) % 180;
    return Math.min(d, 180 - d);
  };
  function nearest(pt, dir) {
    let best = null;
    const cx = Math.floor(pt[0] / CELL);
    const cy = Math.floor(pt[1] / CELL);
    for (let i = -1; i <= 1; i++) {
      for (let j = -1; j <= 1; j++) {
        for (const s of grid.get(key(cx + i, cy + j)) ?? []) {
          const vx = s.b[0] - s.a[0];
          const vy = s.b[1] - s.a[1];
          const len2 = vx * vx + vy * vy || 1;
          const t = Math.max(0, Math.min(1, ((pt[0] - s.a[0]) * vx + (pt[1] - s.a[1]) * vy) / len2));
          const d = Math.hypot(pt[0] - (s.a[0] + t * vx), pt[1] - (s.a[1] + t * vy));
          if (d > MATCH_M || angleGap(bearing(s.a, s.b), dir) > MATCH_DEG) continue;
          if (!best || d < best.d) best = { d, name: s.name };
        }
      }
    }
    return best?.name ?? null;
  }
  const placePts = places.map((p) => ({ ...p, xy: P([p.lng, p.lat]) }));

  const out = {};
  let named = 0;
  for (const f of features) {
    if (f.geometry.type !== "LineString" || f.properties.kind !== "edge") continue;
    const path = f.geometry.coordinates.map(P);
    const cum = [0];
    for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]));
    const L = cum[cum.length - 1];
    const at = (m) => {
      let i = 1;
      while (i < cum.length - 1 && cum[i] < m) i++;
      const t = (m - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
      const a = path[i - 1];
      const b = path[i];
      return { pt: [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])], dir: bearing(a, b) };
    };
    const k = Math.max(3, Math.floor((0.7 * L) / 15));
    const samples = L < 30 ? [L / 2] : Array.from({ length: k }, (_, i) => L * (0.15 + (0.7 * i) / (k - 1)));
    const votes = new Map();
    for (const m of samples) {
      const { pt, dir } = at(m);
      const n = nearest(pt, dir);
      if (n) votes.set(n, (votes.get(n) ?? 0) + 1);
    }
    const [top, count] = [...votes.entries()].sort((p, q) => q[1] - p[1])[0] ?? [null, 0];
    const entry = {};
    if (top && count >= 0.6 * samples.length) {
      entry.n = top;
      named++;
    }
    const mid = at(L / 2).pt;
    let area = null;
    for (const p of placePts) {
      const d = Math.hypot(p.xy[0] - mid[0], p.xy[1] - mid[1]);
      if (d <= AREA_M && (!area || d < area.d)) area = { d, name: p.name };
    }
    if (area) entry.a = area.name;
    if (entry.n || entry.a) out[String(f.properties.edge_id)] = entry;
  }
  return { out, named };
}

const template = await tileTemplate();
const result = {};
for (const [city, files] of Object.entries(NETWORKS)) {
  const features = files.flatMap((p) => JSON.parse(readFileSync(p, "utf8")).features);
  const osm = await readTiles(template, bounds(features));
  const { out, named } = main(features, osm);
  const edges = new Set(features.filter((f) => f.properties.kind === "edge").map((f) => String(f.properties.edge_id))).size;
  console.log(`${city}: ${edges} segments, ${named} matched to a street, ${Object.keys(out).length} with a name or area`);
  result[city] = Object.fromEntries(Object.entries(out).sort(([p], [q]) => p.localeCompare(q)));
}
writeFileSync(OUT, `${JSON.stringify(result, null, 1)}\n`);
console.log(`wrote ${OUT}`);
