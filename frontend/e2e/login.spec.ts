import type { Page, Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { test, expect, SIGNED_IN_USER } from "./fixtures";

// The sign-in flow against a stubbed api-service. The real one (Postgres,
// cookies, lockout) is covered by backend/services/api-gateway/tests/test_auth.py;
// here we care what the browser does with each answer it can give.

const GOOD = { username: "komal", password: "a long enough pass" };

interface Api {
  loginCalls: { username: string; password: string }[];
  signedIn: () => boolean;
}

/** Starts signed out. `/login` accepts GOOD and sets the session flag; `/me`
 * and `/logout` follow it, like the real cookie would. */
async function signedOutApi(
  page: Page,
  opts: { loginStatus?: (n: number) => number; headers?: Record<string, string> } = {},
): Promise<Api> {
  let signedIn = false;
  const api: Api = { loginCalls: [], signedIn: () => signedIn };
  await page.route("**/api/v1/auth/me", (route) =>
    signedIn ? route.fulfill({ json: SIGNED_IN_USER }) : route.fulfill({ status: 401, json: { detail: "Not signed in." } }),
  );
  await page.route("**/api/v1/auth/login", async (route: Route) => {
    const body = route.request().postDataJSON();
    api.loginCalls.push(body);
    const forced = opts.loginStatus?.(api.loginCalls.length);
    if (forced && forced !== 200) {
      return route.fulfill({ status: forced, json: { detail: "x" }, headers: opts.headers ?? {} });
    }
    if (body.username === GOOD.username && body.password === GOOD.password) {
      signedIn = true;
      return route.fulfill({ json: SIGNED_IN_USER });
    }
    return route.fulfill({ status: 401, json: { detail: "Incorrect username or password." } });
  });
  await page.route("**/api/v1/auth/logout", (route) => {
    signedIn = false;
    return route.fulfill({ status: 204, body: "" });
  });
  return api;
}

const username = (page: Page) => page.getByLabel("Username");
const password = (page: Page) => page.getByLabel("Password", { exact: true });
const submit = (page: Page) => page.getByRole("button", { name: /^Sign(ing)? in/ });

async function signIn(page: Page, creds = GOOD) {
  await username(page).fill(creds.username);
  await password(page).fill(creds.password);
  await submit(page).click();
}

test("the console sends signed-out visitors to sign in, then back where they were headed", async ({ page }) => {
  await signedOutApi(page);
  await page.goto("/console/traffic");
  await expect(page).toHaveURL(/\/login\?next=%2Fconsole%2Ftraffic$/);
  await expect(page.getByRole("heading", { name: "Sign in to TRAFFIX" })).toBeVisible();

  await signIn(page);
  await expect(page).toHaveURL(/\/console\/traffic$/);
  await expect(page.locator("#workspace")).toBeVisible();
});

test("a wrong password shows one clear error, clears the field and refocuses it", async ({ page }) => {
  const api = await signedOutApi(page);
  await page.goto("/login");
  await signIn(page, { username: "komal", password: "not the password" });

  await expect(page.getByRole("alert")).toHaveText("Incorrect username or password.");
  await expect(password(page)).toHaveValue("");
  await expect(password(page)).toBeFocused();
  await expect(username(page)).toHaveValue("komal");
  await expect(page).toHaveURL(/\/login$/);
  expect(api.loginCalls).toHaveLength(1);
});

test("empty fields are caught before any request is sent", async ({ page }) => {
  const api = await signedOutApi(page);
  await page.goto("/login");
  await submit(page).click();
  await expect(page.getByText("Enter your username.")).toBeVisible();
  await expect(username(page)).toBeFocused();
  await expect(username(page)).toHaveAttribute("aria-invalid", "true");

  await username(page).fill("komal");
  await expect(page.getByText("Enter your username.")).toBeHidden();
  await submit(page).click();
  await expect(page.getByText("Enter your password.")).toBeVisible();
  await expect(password(page)).toBeFocused();
  expect(api.loginCalls).toHaveLength(0);
});

test("a locked account says how long to wait", async ({ page }) => {
  await signedOutApi(page, { loginStatus: () => 429, headers: { "retry-after": "840" } });
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toContainText("Try again in about 14 minutes.");
});

test("a sign-in service that is down is reported as that, not as a bad password", async ({ page }) => {
  await signedOutApi(page, { loginStatus: () => 503 });
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toContainText("Sign-in is unavailable");
  // the typed password is kept: it was probably right
  await expect(password(page)).toHaveValue(GOOD.password);
});

test("an unreachable server is reported, and a retry can succeed", async ({ page }) => {
  let attempts = 0;
  const api = await signedOutApi(page);
  await page.route("**/api/v1/auth/login", (route) => {
    attempts += 1;
    return attempts === 1 ? route.abort("connectionrefused") : route.fallback();
  });
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toContainText("Can't reach the server");
  await submit(page).click();
  await expect(page).toHaveURL(/\/console$/);
  expect(api.signedIn()).toBe(true);
});

test("a host with no api-service behind /api is not mistaken for a signed-in session", async ({ page }) => {
  // Static hosts answer every unknown path with index.html and a 200.
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>x</title>" }),
  );
  await page.goto("/console");
  await expect(page).toHaveURL(/\/login\?next=%2Fconsole$/);
  await expect(page.getByText("We can't reach the sign-in service.")).toBeVisible();
});

test("signing in twice quickly sends one request", async ({ page }) => {
  const api = await signedOutApi(page);
  await page.route("**/api/v1/auth/login", async (route) => {
    await new Promise((r) => setTimeout(r, 400));
    await route.fallback();
  });
  await page.goto("/login");
  await username(page).fill(GOOD.username);
  await password(page).fill(GOOD.password);
  await password(page).press("Enter");
  await submit(page).click({ force: true });
  await expect(page).toHaveURL(/\/console$/);
  expect(api.loginCalls).toHaveLength(1);
});

test("next only ever leads inside the console", async ({ page }) => {
  await signedOutApi(page);
  await page.goto("/login?next=https%3A%2F%2Fevil.example%2Fphish");
  await signIn(page);
  await expect(page).toHaveURL(/127\.0\.0\.1:4173\/console$/);
});

test("someone already signed in skips the form", async ({ page }) => {
  await page.goto("/login?next=%2Fconsole%2Fanalytics");
  await expect(page).toHaveURL(/\/console\/analytics$/);
});

test("sign out ends the session and the console is closed again", async ({ page }) => {
  await signedOutApi(page);
  await page.goto("/login");
  await signIn(page);
  await expect(page).toHaveURL(/\/console$/);

  await page.getByRole("button", { name: /^Sign out/ }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/console");
  await expect(page).toHaveURL(/\/login\?next=%2Fconsole$/);
});

test("if sign out can't reach the server the session stays and the button says so", async ({ page }) => {
  await signedOutApi(page);
  await page.goto("/login");
  await signIn(page);
  await expect(page).toHaveURL(/\/console$/);

  await page.route("**/api/v1/auth/logout", (route) => route.abort("connectionrefused"));
  await page.getByRole("button", { name: /^Sign out/ }).click();
  await expect(page.getByRole("button", { name: /Couldn't sign out/ })).toBeVisible();
  await expect(page).toHaveURL(/\/console$/);
});

test("the password can be revealed and hidden again", async ({ page }) => {
  await signedOutApi(page);
  await page.goto("/login");
  await password(page).fill("secret value");
  const toggle = page.getByRole("button", { name: "Show password" });
  await expect(password(page)).toHaveAttribute("type", "password");
  await toggle.click();
  await expect(password(page)).toHaveAttribute("type", "text");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await toggle.click();
  await expect(password(page)).toHaveAttribute("type", "password");
});

test("the form fits the screen: nothing scrolls sideways, the button is reachable", async ({ page }, info) => {
  await signedOutApi(page);
  await page.goto("/login");
  await expect(submit(page)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `test-results/login-${info.project.name}.png`, fullPage: true });
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test("the sign-in page has no WCAG 2.2 AA violations, with or without an error", async ({ page }) => {
      await signedOutApi(page);
      await page.goto("/login");
      await expect(submit(page)).toBeVisible();
      // The card and the error notice fade in; axe blends colours mid-fade.
      const scan = async () => {
        await page.waitForTimeout(800);
        return new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      };
      expect((await scan()).violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`))).toEqual([]);

      await signIn(page, { username: "komal", password: "wrong wrong wrong" });
      await expect(page.getByRole("alert")).toBeVisible();
      await submit(page).click(); // empty password now -> inline field error too
      await expect(page.getByText("Enter your password.")).toBeVisible();
      expect((await scan()).violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`))).toEqual([]);
    });
  });
}

// ---------------------------------------------------------------- forgot password

/** Stubs the three reset endpoints. The right code is 123456. */
async function resetApi(page: Page) {
  const calls: string[] = [];
  await page.route("**/api/v1/auth/forgot", (route) => {
    const { username } = route.request().postDataJSON();
    calls.push(`forgot:${username}`);
    return username === "komal"
      ? route.fulfill({ status: 202, json: { detail: "Code sent.", email_hint: "k***@example.org" } })
      : route.fulfill({
          status: 404,
          json: { detail: username.includes("@") ? "That looks like an email address. Enter your username instead." : "No such user. Check your username." },
        });
  });
  await page.route("**/api/v1/auth/forgot/verify", (route) => {
    const { code } = route.request().postDataJSON();
    calls.push(`verify:${code}`);
    return code === "123456"
      ? route.fulfill({ status: 204, body: "" })
      : route.fulfill({ status: 400, json: { detail: "bad" } });
  });
  await page.route("**/api/v1/auth/forgot/reset", (route) => {
    calls.push("reset");
    return route.fulfill({ status: 204, body: "" });
  });
  return calls;
}

test("forgot password: username -> emailed code -> new password -> back to sign in", async ({ page }) => {
  await signedOutApi(page);
  const calls = await resetApi(page);
  await page.goto("/login");
  await page.getByRole("button", { name: "Forgot your password?" }).click();

  await page.getByLabel("Username").fill("nobody");
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByRole("alert")).toContainText("No such user");

  await page.getByLabel("Username").fill("someone@example.org");
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByRole("alert")).toContainText("looks like an email");

  await page.getByLabel("Username").fill("komal");
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByText("We sent a 6-digit code to k***@example.org")).toBeVisible();

  // a wrong code is refused and the form stays on the code step
  const code = page.getByLabel("6-digit code");
  await code.fill("000000");
  await page.getByRole("button", { name: "Verify code" }).click();
  await expect(page.getByRole("alert")).toContainText("incorrect or has expired");

  await code.fill("123456");
  await page.getByRole("button", { name: "Verify code" }).click();
  await page.getByLabel("New password").fill("a brand new password");
  await page.getByRole("button", { name: "Change password" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Password changed" })).toBeVisible();
  await expect(username(page)).toHaveValue("komal");
  expect(calls).toEqual(["forgot:nobody", "forgot:someone@example.org", "forgot:komal", "verify:000000", "verify:123456", "reset"]);
});
