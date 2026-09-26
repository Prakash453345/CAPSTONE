/**
 * Bundle budget: gzipped JS each page downloads before it can render.
 *
 * Summing every chunk in dist/ (the old CI check) counts lazy chunks that
 * never load together, so it could never pass. This follows Vite's manifest
 * instead: for the app entry and each lazy route, it adds up the chunk plus
 * its static imports — what the browser fetches on arrival. Dynamic imports
 * (the three.js globe, split view) are excluded; they load later.
 *
 * Budgets start from Alex Russell's 2024 figure of 365 KiB of gzipped JS for
 * a JS-heavy app interactive in 3 s on a mid-range phone. Map pages get more
 * because MapLibre alone is ~217 KiB gzipped. Tighten these as code shrinks.
 *
 * Run after `npm run build`: node scripts/check-bundle-budget.mjs
 */
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const dist = new URL("../dist/", import.meta.url).pathname;
const manifest = JSON.parse(readFileSync(join(dist, ".vite/manifest.json"), "utf8"));

const KiB = 1024;
const BUDGETS = [
  { name: "App shell (every page)", entry: "index.html", limit: 170 * KiB },
  { name: "Landing", entry: "src/app/landing/LandingPage.tsx", limit: 200 * KiB },
  { name: "Command centre", entry: "src/app/dashboard/DashboardPage.tsx", limit: 410 * KiB },
  { name: "Traffic", entry: "src/app/traffic/TrafficPage.tsx", limit: 410 * KiB },
  { name: "Anomalies", entry: "src/app/anomalies/AnomaliesPage.tsx", limit: 410 * KiB },
  { name: "Emergency", entry: "src/app/emergency/EmergencyPage.tsx", limit: 410 * KiB },
  { name: "Analytics", entry: "src/app/analytics/AnalyticsPage.tsx", limit: 200 * KiB },
  { name: "Settings", entry: "src/app/settings/SettingsPage.tsx", limit: 200 * KiB },
];

const gz = new Map();
const gzipped = (file) => {
  if (!gz.has(file)) gz.set(file, gzipSync(readFileSync(join(dist, file))).length);
  return gz.get(file);
};

/** A chunk plus everything it statically imports, as output file names. */
function closure(key, seen = new Set()) {
  const chunk = manifest[key];
  if (!chunk || seen.has(chunk.file)) return seen;
  seen.add(chunk.file);
  for (const dep of chunk.imports ?? []) closure(dep, seen);
  return seen;
}

const shell = closure("index.html");
let failed = false;
for (const { name, entry, limit } of BUDGETS) {
  if (!manifest[entry]) {
    console.error(`::error::Budget entry not in manifest: ${entry}`);
    failed = true;
    continue;
  }
  // Routes load on top of the shell, so count the shell once with them.
  const files = new Set([...shell, ...closure(entry)]);
  const total = [...files].filter((f) => f.endsWith(".js")).reduce((sum, f) => sum + gzipped(f), 0);
  const ok = total <= limit;
  failed ||= !ok;
  const line = `${name.padEnd(24)} ${(total / KiB).toFixed(1).padStart(6)} KiB / ${limit / KiB} KiB`;
  console.log(`${ok ? "ok  " : "FAIL"} ${line}`);
  if (!ok) console.log(`::error::Bundle budget exceeded — ${line}`);
}
process.exit(failed ? 1 : 0);
