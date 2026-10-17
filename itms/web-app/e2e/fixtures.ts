import { test as base } from "@playwright/test";

/**
 * Hermetic map tiles and weather. CI browsers have no GPU, so drawing live OpenFreeMap
 * vector tiles in software starved the main thread and made unrelated
 * steps (route changes, form submits) miss their waits. Every test gets
 * empty tiles (204) instead: the map still boots, sizes and styles itself,
 * just without basemap geometry. Tests that exercise the basemap register
 * their own route, which Playwright consults first.
 */
const SAMPLE_WEATHER = {
  current: {
    time: "2026-09-28T14:00",
    interval: 900,
    temperature_2m: 31.4,
    precipitation: 0,
    weather_code: 1,
    cloud_cover: 20,
    wind_speed_10m: 9,
    wind_direction_10m: 250,
    visibility: 12000,
    is_day: 1,
  },
  hourly: {
    time: ["2026-09-28T14:00", "2026-09-28T15:00", "2026-09-28T16:00", "2026-09-28T17:00"],
    precipitation_probability: [0, 10, 40, 60],
    weather_code: [1, 2, 61, 63],
  },
};

/** The console sits behind sign-in. Every test starts as a signed-in operator
 * so the workspace specs stay about the workspace; login.spec.ts registers its
 * own routes (consulted first) to exercise the signed-out paths. */
export const SIGNED_IN_USER = { username: "komal", display_name: "Komal S" };

export const test = base.extend<{ hermeticTiles: void }>({
  hermeticTiles: [
    async ({ page }, use) => {
      await page.route("https://tiles.openfreemap.org/planet/**", (route) =>
        route.fulfill({ status: 204, body: "" }),
      );
      // Fixed, dry weather: tests must not depend on the sky over Vijayawada.
      await page.route("https://api.open-meteo.com/**", (route) =>
        route.fulfill({ json: SAMPLE_WEATHER }),
      );
      await page.route("**/api/v1/auth/me", (route) =>
        route.fulfill({ json: SIGNED_IN_USER }),
      );
      await use();
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
