import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// WCAG 2.2 AA gate: every console page, in both themes, with zero axe
// violations. The light theme once shipped contrast failures that a dark-only
// check missed, so both colour schemes are scanned.

const PAGES = [
  "/console",
  "/console/traffic",
  "/console/anomalies",
  "/console/emergency",
  "/console/analytics",
  "/console/settings",
];

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    for (const path of PAGES) {
      test(`${path} has no WCAG 2.2 AA violations`, async ({ page }) => {
        await page.goto(path);
        // The app polls the backend, so "networkidle" never settles; wait
        // for the workspace and its first render instead.
        await page.locator("#workspace").waitFor();
        await page.waitForTimeout(1500);
        const { violations } = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze();
        const summary = violations.flatMap((v) =>
          v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`),
        );
        expect(summary).toEqual([]);
      });
    }
  });
}
