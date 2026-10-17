import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Eye, EyeOff, TriangleAlert } from "lucide-react";
import { BrandMark } from "@/components/branding/BrandMark";
import { Button } from "@/components/ui/button";
import { AuthError } from "@/services/auth/authApi";
import { safeNext } from "@/services/auth/safeRedirect";
import { useAuthStore } from "@/store/authStore";
import { cn } from "@/utils/cn";
import { ForgotFlow } from "@/app/login/ForgotFlow";
import { Signal } from "@/app/login/loginUi";
import { INPUT, LAMP_TEXT, type Lamp } from "@/app/login/loginConsts";

/** What the operator should read for each way a sign-in can fail. */
function messageFor(err: unknown): string {
  if (!(err instanceof AuthError)) return "Something went wrong. Please try again.";
  switch (err.kind) {
    case "invalid":
      return "Incorrect username or password.";
    case "locked": {
      const minutes = err.retryAfterSec ? Math.max(1, Math.ceil(err.retryAfterSec / 60)) : null;
      return `Too many failed attempts. ${minutes ? `Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.` : "Try again later."}`;
    }
    case "network":
      return "Can't reach the server. Check your connection and try again.";
    default:
      return "Sign-in is unavailable right now. Please try again in a moment.";
  }
}

export function LoginPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));

  const status = useAuthStore((s) => s.status);
  const serviceDown = useAuthStore((s) => s.serviceDown);
  const signIn = useAuthStore((s) => s.signIn);
  const check = useAuthStore((s) => s.check);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({});
  const [rechecking, setRechecking] = useState(false);
  // Typed since the last failed attempt, and the brief green "granted" beat.
  const [dirty, setDirty] = useState(false);
  const [granted, setGranted] = useState(false);
  const [hold, setHold] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [forgotLamp, setForgotLamp] = useState<Lamp>("idle");
  const [notice, setNotice] = useState<string | null>(null);

  const usernameRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const uid = useId();
  const usernameId = `${uid}-username`;
  const passwordId = `${uid}-password`;
  const usernameErrId = `${uid}-username-err`;
  const passwordErrId = `${uid}-password-err`;
  const formErrId = `${uid}-form-err`;

  useEffect(() => {
    document.title = "Sign in · TRAFFIX";
    // Put the cursor in the form on desktop; on touch screens that would
    // raise the keyboard over the page before anyone has read it.
    if (window.matchMedia?.("(pointer: fine)").matches) usernameRef.current?.focus();
    return () => abortRef.current?.abort();
  }, []);

  const retryCheck = useCallback(async () => {
    setRechecking(true);
    await check();
    setRechecking(false);
  }, [check]);

  // Already signed in (or just now signed in): go where they were headed.
  if (status === "authed" && !hold) return <Navigate to={next} replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;

    const name = username.trim();
    const errors = {
      username: name ? undefined : "Enter your username.",
      password: password ? undefined : "Enter your password.",
    };
    setFieldErrors(errors);
    setError(null);
    if (errors.username || errors.password) {
      (errors.username ? usernameRef : passwordRef).current?.focus();
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setDirty(false);
    // Hold the redirect so the green lamp is seen before the console opens.
    setHold(true);
    try {
      await signIn(name, password, controller.signal);
      setGranted(true);
      await new Promise((r) => setTimeout(r, 900));
      if (controller.signal.aborted) return;
      // Releasing the hold lets this page redirect itself (store is "authed").
    } catch (err) {
      if (controller.signal.aborted) return; // the page was left mid-request
      setHold(false);
      setError(messageFor(err));
      if (err instanceof AuthError && err.kind === "invalid") {
        setPassword("");
        passwordRef.current?.focus();
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
    setHold(false);
  };

  const trackCaps = (e: KeyboardEvent<HTMLInputElement>) =>
    setCapsLock(e.getModifierState?.("CapsLock") ?? false);

  const lamp: Lamp = granted
    ? "granted"
    : busy
      ? "busy"
      : error && !dirty
        ? "error"
        : username || password
          ? "typing"
          : "idle";
  const describedBy = (field: "username" | "password") =>
    [fieldErrors[field] ? (field === "username" ? usernameErrId : passwordErrId) : null, error ? formErrId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="relative isolate h-full overflow-y-auto bg-background text-foreground">
      <div aria-hidden className="login-backdrop pointer-events-none absolute inset-0 -z-10" />

      <div className="grid min-h-full place-items-center px-4 py-10 sm:py-14">
        <motion.main
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="w-full max-w-[26rem]"
        >
          <div className="mb-6 flex flex-col items-center text-center">
            <BrandMark size="lg" />
            <h1 className="mt-5 text-2xl font-semibold tracking-[-0.02em]">Sign in to TRAFFIX</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Traffic operations for the ITMS platform.
            </p>
          </div>

          <div className="rounded-2xl bg-surface p-6 shadow-elevation-3 sm:p-8">
            <div className="mb-5 flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Operator access
              </span>
              <span className="flex items-center gap-2.5">
                <span role="status" aria-live="polite" className="sr-only">
                  {LAMP_TEXT[forgot ? forgotLamp : lamp]}
                </span>
                <Signal state={forgot ? forgotLamp : lamp} />
              </span>
            </div>

            {serviceDown && status !== "checking" && (
              <div
                role="status"
                className="mb-4 flex items-start gap-2.5 rounded-xl bg-status-warn-muted px-3.5 py-3 text-[13px] text-status-warn"
              >
                <TriangleAlert className="mt-px size-4 shrink-0" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p>We can't reach the sign-in service.</p>
                  <button
                    type="button"
                    onClick={retryCheck}
                    aria-disabled={rechecking}
                    className="mt-1 font-medium underline underline-offset-2 hover:no-underline"
                  >
                    {rechecking ? "Checking…" : "Try again"}
                  </button>
                </div>
              </div>
            )}

            {forgot ? (
              <ForgotFlow
                initialUsername={username}
                onLamp={setForgotLamp}
                onBack={() => setForgot(false)}
                onDone={(name) => {
                  setUsername(name);
                  setPassword("");
                  setError(null);
                  setNotice("Password changed. Sign in with your new password.");
                  setForgot(false);
                }}
              />
            ) : (
              <>
            {notice && (
              <div
                role="status"
                className="mb-4 rounded-xl bg-status-ok-muted px-3.5 py-3 text-[13px] text-status-ok"
              >
                {notice}
              </div>
            )}
            <form onSubmit={onSubmit} noValidate aria-busy={busy} className="flex flex-col gap-4">
              <div>
                <label htmlFor={usernameId} className="mb-1.5 block text-[13px] font-medium">
                  Username
                </label>
                <input
                  ref={usernameRef}
                  id={usernameId}
                  name="username"
                  type="text"
                  value={username}
                  onChange={(e) => {
                    setUsername(e.target.value);
                    setDirty(true);
                    if (fieldErrors.username) setFieldErrors((f) => ({ ...f, username: undefined }));
                  }}
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  maxLength={128}
                  readOnly={busy}
                  aria-invalid={fieldErrors.username ? true : undefined}
                  aria-describedby={describedBy("username")}
                  className={cn(INPUT, fieldErrors.username ? "border-status-critical" : "border-input focus-visible:border-primary")}
                />
                {fieldErrors.username && (
                  <p id={usernameErrId} className="mt-1.5 text-[13px] text-status-critical">
                    {fieldErrors.username}
                  </p>
                )}
              </div>

              <div>
                <label htmlFor={passwordId} className="mb-1.5 block text-[13px] font-medium">
                  Password
                </label>
                <div className="relative">
                  <input
                    ref={passwordRef}
                    id={passwordId}
                    name="password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setDirty(true);
                      if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }));
                    }}
                    onKeyDown={trackCaps}
                    onKeyUp={trackCaps}
                    onBlur={() => setCapsLock(false)}
                    autoComplete="current-password"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    maxLength={256}
                    readOnly={busy}
                    aria-invalid={fieldErrors.password ? true : undefined}
                    aria-describedby={describedBy("password")}
                    className={cn(INPUT, "pr-12", fieldErrors.password ? "border-status-critical" : "border-input focus-visible:border-primary")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label="Show password"
                    aria-pressed={showPassword}
                    className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-xl text-muted-foreground transition-colors hover:text-foreground focus-visible:rounded-r-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    {showPassword ? <EyeOff className="size-[18px]" aria-hidden /> : <Eye className="size-[18px]" aria-hidden />}
                  </button>
                </div>
                {fieldErrors.password && (
                  <p id={passwordErrId} className="mt-1.5 text-[13px] text-status-critical">
                    {fieldErrors.password}
                  </p>
                )}
                {capsLock && (
                  <p className="mt-1.5 text-[13px] text-status-warn">Caps Lock is on.</p>
                )}
              </div>

              {error && (
                <div
                  id={formErrId}
                  role="alert"
                  className="flex items-start gap-2 rounded-xl bg-status-critical-muted px-3.5 py-3 text-[13px] text-status-critical"
                >
                  <TriangleAlert className="mt-px size-4 shrink-0" aria-hidden />
                  <span>{error}</span>
                </div>
              )}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                aria-disabled={busy}
                className="h-11 w-full aria-disabled:cursor-wait aria-disabled:opacity-70"
              >
                {busy && (
                  <span
                    aria-hidden
                    className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                  />
                )}
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </form>

                <p className="mt-5 text-center text-[13px]">
                  <button
                    type="button"
                    onClick={() => {
                      setNotice(null);
                      setForgot(true);
                    }}
                    className="font-medium text-foreground/80 underline underline-offset-2 hover:text-foreground"
                  >
                    Forgot your password?
                  </button>
                </p>
              </>
            )}


          </div>

          <p className="mt-6 text-center text-[13px] text-muted-foreground">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 font-medium text-foreground/80 transition-colors hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" aria-hidden />
              Back to home
            </Link>
          </p>
        </motion.main>
      </div>
    </div>
  );
}
