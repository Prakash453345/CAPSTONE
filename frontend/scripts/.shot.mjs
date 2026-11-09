// Temporary screenshot helper (not committed): node scripts/.shot.mjs <outDir> <tag> [theme] [path...]
import { chromium } from "@playwright/test";
const [out, tag, theme = "dark", ...paths] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome", args: ["--use-angle=metal", "--enable-gpu"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: theme });
const page = await ctx.newPage();
await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: { username: "komal", display_name: "Komal S", role: "operator", unit_id: null } }));
await page.route("**/api/health", (r) => r.abort());
await page.addInitScript(({ t, TAG_COLLAPSE }) => { try { localStorage.setItem("traffix.theme", t); if (TAG_COLLAPSE) localStorage.setItem("traffix.nav.collapsed", "1"); } catch {} }, { t: theme, TAG_COLLAPSE: !!process.env.COLLAPSE });
for (const p of paths.length ? paths : ["/console"]) {
  await page.goto(`http://localhost:${process.env.PORT ?? 5174}` + p, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(Number(process.env.WAIT ?? 12000));
  const name = `${out}/${tag}-${theme}-${p.replace(/\W+/g, "_") || "root"}.png`;
  await page.screenshot({ path: name });
  console.log(name);
}
await browser.close();
