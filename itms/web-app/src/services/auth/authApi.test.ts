import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AuthError,
  fetchSession,
  login,
  logout,
  requestResetCode,
  resetPassword,
  verifyResetCode,
} from "@/services/auth/authApi";
import { useAuthStore } from "@/store/authStore";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });

const html = () =>
  new Response("<!doctype html><html></html>", { status: 200, headers: { "content-type": "text/html" } });

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.setState({ status: "checking", user: null, serviceDown: false });
});

const stub = (impl: () => Promise<Response>) => vi.stubGlobal("fetch", vi.fn(impl));
const kindOf = async (p: Promise<unknown>) => {
  try {
    await p;
  } catch (e) {
    return e instanceof AuthError ? e.kind : `other:${String(e)}`;
  }
  return "resolved";
};

describe("vehicle", () => {
  it("is read for a crew account, and absent otherwise", async () => {
    stub(async () => json(200, { username: "crew1", display_name: "C", role: "responder", unit_id: "EV-001" }));
    expect((await fetchSession())?.unitId).toBe("EV-001");
    stub(async () => json(200, { username: "komal", display_name: "K", role: "operator", unit_id: null }));
    expect((await fetchSession())?.unitId).toBeNull();
    stub(async () => json(200, { username: "old", display_name: "Old" }));
    expect((await fetchSession())?.unitId).toBeNull();
  });

  it("reports what a crew drives, and ignores a kind it does not know", async () => {
    stub(async () => json(200, { username: "p", display_name: "P", role: "responder", unit_id: "unit-police-3", unit_kind: "police" }));
    expect((await fetchSession())?.unitKind).toBe("police");
    stub(async () => json(200, { username: "p", display_name: "P", role: "responder", unit_kind: "tank" }));
    expect((await fetchSession())?.unitKind).toBeNull();
  });
});

describe("role", () => {
  it("is read from the session, and is operator when the server does not say", async () => {
    stub(async () => json(200, { username: "crew1", display_name: "Crew 1", role: "responder" }));
    expect((await fetchSession())?.role).toBe("responder");
    stub(async () => json(200, { username: "old", display_name: "Old" }));
    expect((await fetchSession())?.role).toBe("operator");
    stub(async () => json(200, { username: "odd", display_name: "Odd", role: "admin" }));
    expect((await fetchSession())?.role).toBe("operator");
  });
});

describe("fetchSession", () => {
  it("returns the user, falling back to the username for the display name", async () => {
    stub(async () => json(200, { username: "komal", display_name: "Komal S" }));
    expect(await fetchSession()).toEqual({ username: "komal", displayName: "Komal S", role: "operator", unitId: null, unitKind: null });
    stub(async () => json(200, { username: "komal", display_name: "" }));
    expect(await fetchSession()).toEqual({ username: "komal", displayName: "komal", role: "operator", unitId: null, unitKind: null });
  });

  it("is null on 401 and calls the proxied api path without caching", async () => {
    stub(async () => json(401, { detail: "Not signed in." }));
    expect(await fetchSession()).toBeNull();
    const [url, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/me");
    expect(init.cache).toBe("no-store");
  });

  it("treats a static host's index.html (200) as unavailable, never as signed in", async () => {
    stub(async () => html());
    expect(await kindOf(fetchSession())).toBe("unavailable");
  });

  it.each([
    ["a 5xx", () => json(503, { detail: "x" })],
    ["JSON without a username", () => json(200, { ok: true })],
    ["an empty username", () => json(200, { username: "" })],
  ])("is unavailable for %s", async (_name, make) => {
    stub(async () => make());
    expect(await kindOf(fetchSession())).toBe("unavailable");
  });

  it("is a network error when the request fails", async () => {
    stub(async () => Promise.reject(new TypeError("Failed to fetch")));
    expect(await kindOf(fetchSession())).toBe("network");
  });
});

describe("login", () => {
  it("posts credentials as JSON and returns the user", async () => {
    stub(async () => json(200, { username: "komal", display_name: "Komal" }));
    expect(await login("komal", "pw")).toEqual({ username: "komal", displayName: "Komal", role: "operator", unitId: null, unitKind: null });
    const [url, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ username: "komal", password: "pw" });
    expect(init.credentials).toBe("same-origin");
  });

  it("maps 401 to invalid", async () => {
    stub(async () => json(401, { detail: "no" }));
    expect(await kindOf(login("a", "b"))).toBe("invalid");
  });

  it("maps 429 to locked and carries Retry-After", async () => {
    stub(async () => json(429, { detail: "no" }, { "retry-after": "600" }));
    const err = await login("a", "b").catch((e) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(err.kind).toBe("locked");
    expect(err.retryAfterSec).toBe(600);
  });

  it("ignores a missing or nonsense Retry-After", async () => {
    stub(async () => json(429, {}, { "retry-after": "soon" }));
    const err = await login("a", "b").catch((e) => e);
    expect(err.retryAfterSec).toBeUndefined();
  });

  it.each([404, 405, 500, 503])("maps %i to unavailable", async (status) => {
    stub(async () => json(status, { detail: "x" }));
    expect(await kindOf(login("a", "b"))).toBe("unavailable");
  });

  it("maps a refused connection to network", async () => {
    stub(async () => Promise.reject(new TypeError("Failed to fetch")));
    expect(await kindOf(login("a", "b"))).toBe("network");
  });
});

describe("logout", () => {
  it("resolves on 204 and rejects when the server did not clear the session", async () => {
    stub(async () => new Response(null, { status: 204 }));
    await expect(logout()).resolves.toBeUndefined();
    stub(async () => json(500, {}));
    expect(await kindOf(logout())).toBe("unavailable");
  });
});

describe("authStore", () => {
  it("check(): 200 -> authed, 401 -> anon", async () => {
    stub(async () => json(200, { username: "komal", display_name: "K" }));
    await useAuthStore.getState().check();
    expect(useAuthStore.getState()).toMatchObject({ status: "authed", serviceDown: false });

    stub(async () => json(401, {}));
    await useAuthStore.getState().check();
    expect(useAuthStore.getState()).toMatchObject({ status: "anon", user: null });
  });

  it("check(): an unreachable service means anon + serviceDown", async () => {
    stub(async () => Promise.reject(new TypeError("down")));
    await useAuthStore.getState().check();
    expect(useAuthStore.getState()).toMatchObject({ status: "anon", serviceDown: true });
  });

  it("check(): a transient failure does not sign out a confirmed session", async () => {
    useAuthStore.setState({ status: "authed", user: { username: "komal", displayName: "K", role: "operator", unitId: null, unitKind: null } });
    stub(async () => Promise.reject(new TypeError("down")));
    await useAuthStore.getState().check();
    expect(useAuthStore.getState().status).toBe("authed");
  });

  it("concurrent check() calls share one request", async () => {
    stub(async () => json(401, {}));
    await Promise.all([useAuthStore.getState().check(), useAuthStore.getState().check()]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("a /me answer that was in flight during sign-in cannot overwrite it", async () => {
    let release!: (r: Response) => void;
    const slowMe = new Promise<Response>((r) => (release = r));
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/me") ? slowMe : Promise.resolve(json(200, { username: "komal", display_name: "K" })),
      ),
    );
    const pending = useAuthStore.getState().check();
    await useAuthStore.getState().signIn("komal", "pw");
    release(json(401, {})); // the pre-login answer arrives late
    await pending;
    expect(useAuthStore.getState().status).toBe("authed");
  });

  it("signIn failure leaves the store untouched; signOut failure keeps the session", async () => {
    stub(async () => json(401, {}));
    await expect(useAuthStore.getState().signIn("a", "b")).rejects.toBeInstanceOf(AuthError);
    expect(useAuthStore.getState().status).toBe("checking");

    useAuthStore.setState({ status: "authed", user: { username: "komal", displayName: "K", role: "operator", unitId: null, unitKind: null } });
    stub(async () => json(500, {}));
    await expect(useAuthStore.getState().signOut()).rejects.toBeInstanceOf(AuthError);
    expect(useAuthStore.getState().status).toBe("authed");

    stub(async () => new Response(null, { status: 204 }));
    await useAuthStore.getState().signOut();
    expect(useAuthStore.getState()).toMatchObject({ status: "anon", user: null });
  });
});

describe("forgot password", () => {
  const empty = (status: number) => new Response(null, { status });

  it("requestResetCode returns the masked address and maps unknown / no-email accounts", async () => {
    stub(async () => json(202, { detail: "Code sent.", email_hint: "k***@x.org" }));
    expect(await requestResetCode("komal")).toBe("k***@x.org");
    stub(async () => json(404, { detail: "x" }));
    expect(await kindOf(requestResetCode("nobody"))).toBe("unknown");
    stub(async () => json(409, { detail: "x" }));
    expect(await kindOf(requestResetCode("komal"))).toBe("noemail");
    stub(async () => html()); // a static host with no api-service
    expect(await kindOf(requestResetCode("komal"))).toBe("unavailable");
  });

  it("verifyResetCode maps a refused code to badcode", async () => {
    stub(async () => empty(204));
    await expect(verifyResetCode("komal", "123456")).resolves.toBeUndefined();
    stub(async () => json(400, { detail: "x" }));
    expect(await kindOf(verifyResetCode("komal", "000000"))).toBe("badcode");
    stub(async () => json(503, {}));
    expect(await kindOf(verifyResetCode("komal", "123456"))).toBe("unavailable");
  });

  it("resetPassword sends the code and password, and surfaces why a password was refused", async () => {
    stub(async () => empty(204));
    await resetPassword("komal", "123456", "a long enough pass");
    const [url, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/forgot/reset");
    expect(JSON.parse(String(init.body))).toEqual({
      username: "komal",
      code: "123456",
      new_password: "a long enough pass",
    });

    stub(async () => json(422, { detail: "Password must be at least 10 characters." }));
    await expect(resetPassword("komal", "123456", "short")).rejects.toMatchObject({
      kind: "weak",
      detail: "Password must be at least 10 characters.",
    });
    stub(async () => json(400, {}));
    expect(await kindOf(resetPassword("komal", "000000", "a long enough pass"))).toBe("badcode");
  });
});
