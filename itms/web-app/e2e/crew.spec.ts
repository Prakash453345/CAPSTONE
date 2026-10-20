import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// The crew page for emergency-vehicle crews. With no backend the app runs its
// demo data, which includes one simulated ambulance on a mission ("Ambulance 1"),
// so these specs follow that mission end to end.

const next = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Next instruction" });

test("a crew sees their next turn, the signals ahead, what is on the road, and trip progress", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/crew");

  await expect(page.getByRole("heading", { name: "TRAFFIX Crew" })).toBeVisible();
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
  await page.goto("/crew");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Show all directions" }).click();
  await expect(page.getByRole("heading", { name: "All directions" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: /Arrive at the destination/ })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Signals ahead" })).toBeVisible();
});

test("the vehicle picker lists only units that dispatch has used, grouped by kind", async ({ page }) => {
  await page.goto("/crew");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Vehicle", { exact: true }).selectOption({ label: "Ambulance 2" });
  await expect(page.getByText("Ambulance 2 is standing by")).toBeVisible();
  await expect(next(page)).toBeHidden();
  await page.getByLabel("Vehicle", { exact: true }).selectOption({ label: "Ambulance 1 · on a mission" });
  await expect(next(page)).toBeVisible();
});

test("voice guidance can be switched off and on", async ({ page }) => {
  await page.goto("/crew");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  const off = page.getByRole("button", { name: "Turn voice guidance off" });
  // Browsers without speech synthesis simply do not offer the control.
  test.skip((await off.count()) === 0, "no speech synthesis in this browser");
  await expect(off).toHaveAttribute("aria-pressed", "true");
  await off.click();
  await expect(page.getByRole("button", { name: "Turn voice guidance on" })).toHaveAttribute("aria-pressed", "false");
});

test("the page fits the screen: nothing scrolls sideways and the trip bar is reachable", async ({ page }) => {
  await page.goto("/crew");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const trip = page.getByRole("region", { name: "Trip progress" });
  await expect(trip).toBeInViewport();
});

test("signed-out visitors are sent to sign in and back to the crew page", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 401, json: { detail: "Not signed in." } }));
  await page.goto("/crew");
  await expect(page).toHaveURL(/\/login\?next=%2Fcrew$/);
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test("the crew page has no WCAG 2.2 AA violations", async ({ page }) => {
      await page.goto("/crew");
      await expect(next(page)).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1000);
      const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`))).toEqual([]);
    });
  });
}

// ------------------------------------------------------------------ roles

// In the browser demo the simulated ambulance is "amb-01".
const CREW = { username: "crew1", display_name: "Crew One", role: "responder", unit_id: "amb-01", unit_kind: "ambulance" };

test("a crew account that opens the console is sent to the crew page", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: CREW }));
  await page.goto("/console/traffic");
  await expect(page).toHaveURL(/\/crew$/);
  await expect(page.getByRole("heading", { name: "TRAFFIX Crew" })).toBeVisible();
  // and is not offered the operator console from there
  await expect(page.getByRole("link", { name: "Open the operator console" })).toHaveCount(0);
});

test("an operator can open the crew page and is offered the way back", async ({ page }) => {
  await page.goto("/crew");
  await expect(page.getByRole("heading", { name: "TRAFFIX Crew" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the operator console" })).toBeVisible();
});

test("signing in lands each account on its own page", async ({ page }) => {
  for (const [role, expected] of [
    ["responder", /\/crew$/],
    ["operator", /\/console$/],
  ] as const) {
    let signedIn = false;
    const user = role === "responder" ? CREW : { username: "komal", display_name: "Komal S", role };
    await page.unroute("**/api/v1/auth/me").catch(() => undefined);
    await page.route("**/api/v1/auth/me", (route) =>
      signedIn ? route.fulfill({ json: user }) : route.fulfill({ status: 401, json: { detail: "Not signed in." } }),
    );
    await page.route("**/api/v1/auth/login", (route) => {
      signedIn = true;
      return route.fulfill({ json: user });
    });
    await page.goto("/login");
    await page.getByLabel("Username").fill(user.username);
    await page.getByLabel("Password", { exact: true }).fill("a long enough pass");
    await page.getByRole("button", { name: /^Sign in/ }).click();
    await expect(page).toHaveURL(expected, { timeout: 15_000 });
  }
});

test("a crew account sees only its own vehicle: no picker, and it follows its own call", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: CREW }));
  await page.goto("/crew");
  await expect(next(page)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByText("Vehicle:")).toBeAttached();
  // ...and is shown what kind of crew it is
  await expect(page.getByText("Ambulance crew · Ambulance 1", { exact: true })).toBeVisible();
});

test("a crew account with no vehicle linked is told to ask dispatch, and sees no one else's", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: { ...CREW, unit_id: null } }));
  await page.goto("/crew");
  await expect(page.getByText("No vehicle is linked to your account")).toBeVisible();
  await expect(next(page)).toBeHidden();
  await expect(page.getByRole("combobox")).toHaveCount(0);
});
