import { chromium } from "@playwright/test";
const [out, theme = "dark"] = process.argv.slice(2);
const b = await chromium.launch({ channel: "chrome" });
const ctx = await b.newContext({ viewport: { width: 1440, height: 760 }, deviceScaleFactor: 2, colorScheme: theme });
const page = await ctx.newPage();
await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: { username: "komal", display_name: "Komal S", role: "operator", unit_id: null } }));
await page.route("**/api/health", (r) => r.abort());
await page.addInitScript((t) => localStorage.setItem("traffix.theme", t), theme);
await page.goto("http://localhost:5174/console");
await page.waitForTimeout(9000);
const shots = [
  ["notifications", () => page.getByRole("button", { name: "Notifications" }).click()],
  ["status", () => page.getByRole("button", { name: /Data and connection/ }).click()],
  ["weather", () => page.getByRole("button", { name: /^Weather:/ }).click()],
];
for (const [name, open] of shots) {
  await open(); await page.waitForTimeout(700);
  await page.screenshot({ path: `${out}/pop-${theme}-${name}.png`, clip: { x: 560, y: 0, width: 880, height: 620 } });
  await page.keyboard.press("Escape"); await page.mouse.click(700, 500); await page.waitForTimeout(400);
}
// Sidebar on a short window, scrolled: the highlight must stay on its row.
await page.setViewportSize({ width: 1440, height: 560 });
await page.goto("http://localhost:5174/console/traffic"); await page.waitForTimeout(4000);
await page.locator('nav[aria-label="Primary"] .overflow-y-auto').evaluate((el) => (el.scrollTop = 40));
await page.waitForTimeout(300);
await page.screenshot({ path: `${out}/pop-${theme}-sidebar.png`, clip: { x: 0, y: 0, width: 300, height: 560 } });
await b.close();
