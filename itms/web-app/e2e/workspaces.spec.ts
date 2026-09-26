import { test, expect, type Page } from "@playwright/test";

// "/" is the public landing page; the operator workspace lives under
// "/console". These specs drive the workspace, so they enter there directly.

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
  await expect(
    page.getByRole("heading", { name: "A city in motion. In view." }),
  ).toBeVisible();
  await expect(
    page.getByText("DEMO ENVIRONMENT", { exact: false }),
  ).toBeVisible();
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
  await navigate(page, "Traffic Management");
  await page
    .getByRole("textbox", { name: "Search roads" })
    .fill("no-such-road");
  await expect(
    page.getByText("No matching roads.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Search roads" }).fill("177626285");
  await expect(
    page.getByRole("button", { name: /Road -177626285/ }),
  ).toBeVisible();
  await navigate(page, "Anomaly Detection");
  await expect(
    page.getByRole("heading", { name: "Incident review" }),
  ).toBeVisible();
  await expect(
    page.getByText("Demo report · review disabled").first(),
  ).toBeVisible();
  await navigate(page, "Emergency Response");
  await expect(
    page.getByRole("heading", { name: "Emergency requests" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Emergency response", exact: true })
    .click();
  await page
    .getByLabel("Source road", { exact: true })
    .selectOption("-177626285");
  await page
    .getByLabel("Destination road", { exact: true })
    .selectOption("-343269496");
  await page
    .getByRole("button", { name: "Calculate route", exact: true })
    .click();
  await expect(
    page.getByText("Demo is read-only.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await navigate(page, "Analytics");
  await expect(
    page.getByRole("heading", { name: "Patterns in motion." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "15 min", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "15 min", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
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
      expect(route.request().headers()["x-api-key"]).toBe("browser-test-key");
      expect(route.request().postDataJSON().actor).toBe("operator:test");
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
  await page.getByRole("radio", { name: "Live", exact: true }).click();
  await expect.poll(() => Boolean(send)).toBe(true);
  await expect(
    page.getByText("Awaiting telemetry", { exact: false }),
  ).toBeVisible();
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
  await expect(page.getByText(/Updated \ds ago/)).toBeVisible();
  await navigate(page, "Anomaly Detection");
  await page.getByRole("button", { name: "Review & confirm" }).click();
  await page.getByLabel("Operator identity").fill("operator:test");
  await page.getByLabel("API key", { exact: true }).fill("browser-test-key");
  await page.getByRole("button", { name: "Submit confirm" }).click();
  // The card flips to "confirmed" once the (mocked) API answers; slow CI
  // runners have missed the default 5 s.
  await expect(page.getByText("confirmed", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await navigate(page, "Command Center");
  await expect(page.getByText(/Stale · last update/)).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("radio", { name: "Demo", exact: true }).click();
  await expect(
    page.getByText("DEMO ENVIRONMENT", { exact: false }),
  ).toBeVisible();
});

test("map fills its panel on every map page", async ({ page }) => {
  // Regression: lazy-loaded maplibre-gl.css once overrode the container's
  // positioning and collapsed the map to 0 px while every control still showed.
  for (const path of ["/console", "/console/traffic", "/console/anomalies", "/console/emergency"]) {
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
