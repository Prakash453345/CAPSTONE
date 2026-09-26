import { test as base } from "@playwright/test";

/**
 * Hermetic map tiles. CI browsers have no GPU, so drawing live OpenFreeMap
 * vector tiles in software starved the main thread and made unrelated
 * steps (route changes, form submits) miss their waits. Every test gets
 * empty tiles (204) instead: the map still boots, sizes and styles itself,
 * just without basemap geometry. Tests that exercise the basemap register
 * their own route, which Playwright consults first.
 */
export const test = base.extend<{ hermeticTiles: void }>({
  hermeticTiles: [
    async ({ page }, use) => {
      await page.route("https://tiles.openfreemap.org/planet/**", (route) =>
        route.fulfill({ status: 204, body: "" }),
      );
      await use();
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
