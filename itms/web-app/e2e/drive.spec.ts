import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// The Drive page for emergency-vehicle crews. With no backend the app runs its
// demo data, which includes one simulated ambulance on a mission ("Ambulance 1"),
// so these specs follow that mission end to end.

const next = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Next instruction" });

test("a crew sees their next turn, the signals ahead, what is on the road, and trip progress", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/drive");

  await expect(page.getByRole("heading", { name: "TRAFFIX Drive" })).toBeVisible();
  // The unit with a call is chosen for them.
  await expect(page.getByLabel("Vehicle", { exact: true })).toHaveValue(/amb-01/, { timeout: 15_000 });
  await expect(next(page)).toBeVisible();
  await expect(next(page)).toContainText(/\d+(\.\d)? ?(m|km)/);
  await expect(page.getByRole("heading", { name: "Signals ahead" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "On your route" })).toBeVisible();
  const trip = page.getByRole("region", { name: "Trip progress" });
  await expect(trip).toContainText("Arrive");
  await expect(trip).toContainText("Time left");
  // Honest about what it is showing.
  await expect(page.getByText("Demo", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("all directions opens over the cards and closes again", async ({ page }) => {
  await page.goto("/drive");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Show all directions" }).click();
  await expect(page.getByRole("heading", { name: "All directions" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: /Arrive at the destination/ })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Signals ahead" })).toBeVisible();
});

test("a unit with no call is told it is standing by, and can switch back", async ({ page }) => {
  await page.goto("/drive");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Vehicle", { exact: true }).selectOption({ label: "Ambulance 12" });
  await expect(page.getByText("Ambulance 12 is standing by")).toBeVisible();
  await expect(next(page)).toBeHidden();
  await page.getByLabel("Vehicle", { exact: true }).selectOption({ label: "Ambulance 1 · on a mission" });
  await expect(next(page)).toBeVisible();
});

test("voice guidance can be switched off and on", async ({ page }) => {
  await page.goto("/drive");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  const off = page.getByRole("button", { name: "Turn voice guidance off" });
  // Browsers without speech synthesis simply do not offer the control.
  test.skip((await off.count()) === 0, "no speech synthesis in this browser");
  await expect(off).toHaveAttribute("aria-pressed", "true");
  await off.click();
  await expect(page.getByRole("button", { name: "Turn voice guidance on" })).toHaveAttribute("aria-pressed", "false");
});

test("the page fits the screen: nothing scrolls sideways and the trip bar is reachable", async ({ page }) => {
  await page.goto("/drive");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const trip = page.getByRole("region", { name: "Trip progress" });
  await expect(trip).toBeInViewport();
});

test("signed-out visitors are sent to sign in and back to the Drive page", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 401, json: { detail: "Not signed in." } }));
  await page.goto("/drive");
  await expect(page).toHaveURL(/\/login\?next=%2Fdrive$/);
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test("the Drive page has no WCAG 2.2 AA violations", async ({ page }) => {
      await page.goto("/drive");
      await expect(next(page)).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1000);
      const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`))).toEqual([]);
    });
  });
}
