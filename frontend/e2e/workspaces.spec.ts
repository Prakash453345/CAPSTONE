import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";

// "/" is the public landing page; the operator workspace lives under
// "/console". These specs drive the workspace, so they enter there directly.

/** The data-status chip in the top bar (and floating on the full-screen map). */
function statusChip(page: Page) {
  return page.getByRole("button", { name: /Data and connection/ }).first();
}

async function openStatus(page: Page) {
  await statusChip(page).click();
  await expect(page.getByRole("dialog", { name: "Data and connection" })).toBeVisible();
}

async function navigate(page: Page, label: string) {
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await menu.click();
  await page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: label, exact: true })
    .click();
}

test("map, operational routes, analytics and CSV stay integrated", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/console");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(statusChip(page)).toContainText("Demo data");
  await expect(
    page.getByRole("button", { name: "Map layers", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Map layers", exact: true }).click();
  const vehicles = page.getByRole("switch", { name: "Vehicles", exact: true });
  await vehicles.click();
  await expect(vehicles).toHaveAttribute("aria-checked", "false");
  await vehicles.click();
  await expect(vehicles).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Map layers", exact: true }).click();
  await page.screenshot({
    path: `test-results/overview-${info.project.name}.png`,
    fullPage: true,
  });
  await navigate(page, "Traffic");
  await page.getByRole("textbox", { name: "Find a street" }).fill("no-such-road");
  await expect(page.getByText("No matching streets")).toBeVisible();
  await page.getByRole("textbox", { name: "Find a street" }).fill("eat");
  await expect(page.getByRole("button", { name: /Eat Street/ })).toBeVisible();
  await navigate(page, "Incidents");
  await expect(
    page.getByRole("heading", { name: "Incident review" }),
  ).toBeVisible();
  await expect(
    page.getByText("Demo report. Review is disabled.").first(),
  ).toBeVisible();
  await navigate(page, "Emergency");
  await expect(
    page.getByRole("heading", { name: "Emergency requests" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Dispatch", exact: true }).click();
  // Destination only: the nearest free crew drives from where it is.
  await page.getByPlaceholder("Search a road").fill("eat");
  await page.getByRole("option", { name: /Eat Street/ }).first().click();
  await page.getByRole("button", { name: "Request ambulance", exact: true }).click();
  // The demo answers the request itself: a crew is offered the call.
  await expect(page.getByText(/^(Asking|Finding the nearest)/).first()).toBeVisible();
  await page.getByRole("button", { name: "Cancel request", exact: true }).click();
  await navigate(page, "Analytics");
  await expect(
    page.getByRole("heading", { name: "Session analytics" }),
  ).toBeVisible();
  await page.getByRole("radio", { name: "15 min", exact: true }).click();
  await expect(
    page.getByRole("radio", { name: "15 min", exact: true }),
  ).toHaveAttribute("aria-checked", "true");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export observations" }).click();
  expect((await download).suggestedFilename()).toContain("simulation-session");
  await navigate(page, "Settings");
  await expect(page.getByRole("heading", { name: "Map layers" })).toBeVisible();
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("live stream freshness, incident review and source isolation", async ({
  page,
}) => {
  let send: ((message: string) => void) | undefined;
  await page.routeWebSocket("**/ws/v1/stream", (ws) => {
    send = (message) => ws.send(message);
  });
  await page.route("**/api/v1/incidents", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/v1/incidents/live-incident/confirm",
    async (route) => {
      expect(route.request().headers()["x-api-key"]).toBeUndefined(); // the session is the credential
      expect(route.request().postDataJSON().actor).toMatch(/^operator:/);
      await route.fulfill({
        json: {
          incident_id: "live-incident",
          intersection_id: "1880441505",
          first_seen_ms: Date.now(),
          state: "CONFIRMED",
          fused_probability: 0.85,
          classification: "STALL",
        },
      });
    },
  );
  await page.goto("/console");
  await openStatus(page);
  await page.getByRole("radio", { name: "Live", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect.poll(() => Boolean(send)).toBe(true);
  await expect(statusChip(page)).toHaveAccessibleName(/Awaiting telemetry/);
  send!(
    JSON.stringify({
      event_type: "ApproachState",
      payload: { movement_id: "-177626285", occupancy: 0.45 },
    }),
  );
  send!(
    JSON.stringify({
      event_type: "IncidentCandidate",
      payload: {
        incident_id: "live-incident",
        intersection_id: "1880441505",
        detected_at: Date.now(),
        fused_probability: 0.85,
      },
    }),
  );
  await expect(statusChip(page)).toHaveAccessibleName(/Updated (just now|\d+s ago)/);
  await navigate(page, "Incidents");
  await page.getByRole("button", { name: "Review & confirm" }).click();
  await page.getByRole("button", { name: "Submit confirm" }).click();
  // The card flips to "confirmed" once the (mocked) API answers; slow CI
  // runners have missed the default 5 s.
  await expect(page.getByText("confirmed", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await navigate(page, "Overview");
  await expect(statusChip(page)).toHaveAccessibleName(/Stale data/, {
    timeout: 15_000,
  });
  await openStatus(page);
  await page.getByRole("radio", { name: "Demo", exact: true }).click();
  await expect(
    page.getByText("Demo environment.", { exact: false }),
  ).toBeVisible();
});

test("road place card opens from search and starts operator actions", async ({ page }) => {
  await page.goto("/console/traffic");
  const search = page.getByRole("combobox", { name: "Search the road network" });
  await search.fill("177626285");
  await search.press("Enter");
  const card = page.getByRole("region", { name: "Eat Street details" });
  await expect(card).toBeVisible();
  await expect(card.getByText(/Traffic is flowing|Slow traffic|Heavy traffic|No live data/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);

  // "Report" hands the road straight to the anomaly form.
  await search.fill("177626285");
  await search.press("Enter");
  await card.getByRole("button", { name: "Report" }).click();
  await expect(card).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Report a disruption" })).toBeVisible();
  await expect(page.getByText(/Eat Street/).first()).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).first().click();

  // "Send help" opens the request with the road as the destination.
  await search.fill("177626285");
  await search.press("Enter");
  await card.getByRole("button", { name: "Send help" }).click();
  await expect(page.getByRole("heading", { name: "Send help" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Change location" })).toBeVisible();
});

test("weather chip shows live conditions, demo presets and a layer switch", async ({ page }) => {
  await page.goto("/console/traffic");
  const chip = page.getByRole("button", { name: /^Weather: Clear, 31°/ });
  await expect(chip).toBeVisible();
  await chip.click();
  const panel = page.getByRole("dialog", { name: "Weather details" });
  await expect(panel.getByText("Open-Meteo.com")).toBeVisible();
  await expect(panel.getByRole("list", { name: "Next hours" })).toBeVisible();

  // A presenter can force a storm: advice appears and rain is drawn.
  await panel.getByRole("radio", { name: "Storm" }).click();
  await expect(panel.getByText(/Storm: expect slower traffic/)).toBeVisible();
  await expect(page.locator("canvas:not(.maplibregl-canvas)")).toHaveCount(1);
  await panel.getByRole("radio", { name: "Live" }).click();
  await page.keyboard.press("Escape");
  await expect(page.locator("canvas:not(.maplibregl-canvas)")).toHaveCount(0);

  // The Layers menu turns weather off entirely.
  await page.getByRole("button", { name: "Map layers", exact: true }).click();
  await page.getByRole("switch", { name: "Weather", exact: true }).click();
  await expect(page.getByRole("button", { name: /^Weather:/ })).toHaveCount(0);
});

test("split view maps keep their own panels", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "split view is a desktop layout");
  await page.goto("/console/traffic");
  await openStatus(page);
  await page.getByRole("radio", { name: "Split", exact: true }).click();
  await expect(page.locator(".maplibregl-map")).toHaveCount(2);
  await page.getByRole("button", { name: /^Weather:/ }).last().click();
  await expect(page.getByRole("dialog", { name: "Weather details" })).toHaveCount(1);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Map legend" }).first().click();
  await expect(page.locator('[aria-label="Map legend"][aria-expanded="true"]')).toHaveCount(1);
});

test("explore map opens full screen and back returns", async ({ page }) => {
  await page.goto("/console");
  await page.getByRole("button", { name: "Full screen map", exact: true }).click();
  await expect(page).toHaveURL(/\/console\/map$/);
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  // The data status stays visible even in full screen.
  await expect(statusChip(page)).toContainText("Demo data");
  await expect
    .poll(async () => (await page.locator(".maplibregl-map").boundingBox())?.height ?? 0)
    .toBeGreaterThan(600);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(/\/console$/);

  // Opened directly (no history), exit falls back to the command centre.
  await page.goto("/console/map");
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page).toHaveURL(/\/console$/);
});

test("map fills its panel on every map page", async ({ page }) => {
  // Regression: lazy-loaded maplibre-gl.css once overrode the container's
  // positioning and collapsed the map to 0 px while every control still showed.
  for (const path of ["/console", "/console/traffic", "/console/anomalies", "/console/emergency", "/console/map"]) {
    await page.goto(path);
    const canvas = page.locator("canvas.maplibregl-canvas").first();
    await expect(canvas).toBeVisible();
    const map = await page.locator(".maplibregl-map").first().boundingBox();
    const panel = await page.locator(".maplibregl-map").first().locator("..").boundingBox();
    expect(map?.height ?? 0, `${path} map height`).toBeGreaterThan(200);
    expect(Math.abs((map?.height ?? 0) - (panel?.height ?? 0)), `${path} map fills panel`).toBeLessThan(2);
  }
});

test("blocked basemap does not block bundled geometry or map controls", async ({
  page,
}) => {
  await page.route("https://tiles.openfreemap.org/**", (r) => r.abort());
  await page.goto("/console");
  await expect(
    page.getByRole("button", { name: "Zoom in", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Some map resources are unavailable.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(page.getByText("loading map…")).toHaveCount(0);
});

test("mobile drawer keyboard focus and reduced-motion preference", async ({
  page,
}, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/console");
  expect(
    await page
      .locator(".overview-page")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  if (info.project.name === "mobile") {
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Navigation" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Navigation" })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "Open navigation", exact: true }),
    ).toBeFocused();
  }
});

test("a two-finger slide pans the map; a pinch still zooms", async ({ page }) => {
  await page.goto("/console/map");
  const canvas = page.locator("canvas.maplibregl-canvas").first();
  await expect(canvas).toBeVisible();
  const scale = page.locator(".maplibregl-ctrl-scale");
  await expect(scale).toBeVisible();
  const wheel = (init: WheelEventInit) =>
    canvas.evaluate((el, i) => {
      const e = new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 300, clientY: 300, ...i });
      el.dispatchEvent(e);
      return e.defaultPrevented;
    }, init);

  const before = await scale.textContent();
  // Smooth, fractional deltas with a sideways part: a trackpad slide.
  expect(await wheel({ deltaX: 12, deltaY: 40 })).toBe(true);
  await page.waitForTimeout(300);
  expect(await scale.textContent()).toBe(before);

  // ctrl+wheel is how browsers report a pinch.
  for (let i = 0; i < 6; i++) await wheel({ deltaY: -60, ctrlKey: true });
  await expect.poll(() => scale.textContent()).not.toBe(before);
});

test("the report button stays on screen in a short window", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/console/traffic");
  const search = page.getByRole("combobox", { name: "Search the road network" });
  await search.fill("177626285");
  await search.press("Enter");
  await page.getByRole("region", { name: "Eat Street details" }).getByRole("button", { name: "Report" }).click();
  const submit = page.getByRole("button", { name: /^Report / }).last();
  await expect(submit).toBeVisible();
  const box = await submit.boundingBox();
  expect(box && box.y + box.height).toBeLessThanOrEqual(640);
});
