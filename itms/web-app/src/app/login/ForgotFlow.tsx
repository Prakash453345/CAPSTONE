import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, Eye, EyeOff, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthError, requestResetCode, resetPassword, verifyResetCode } from "@/services/auth/authApi";
import { INPUT, type Lamp } from "@/app/login/loginConsts";
import { cn } from "@/utils/cn";

const RESEND_SECONDS = 60;
const MIN_PASSWORD = 10;

type Step = "user" | "code" | "password";

function messageFor(err: unknown): string {
  if (!(err instanceof AuthError)) return "Something went wrong. Please try again.";
  switch (err.kind) {
    case "badcode":
      return "That code is incorrect or has expired. Check it, or request a new one.";
    case "unknown":
      return "No account found with that username. Use your username, not your email.";
    case "noemail":
      return "That account has no email on file. Ask an administrator to reset your password.";
    case "weak":
      return err.detail ?? `Choose a password of at least ${MIN_PASSWORD} characters.`;
    case "network":
      return "Can't reach the server. Check your connection and try again.";
    default:
      return "This isn't available right now. Please try again in a moment.";
  }
}

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

/**
 * Forgot password, in three steps on the sign-in card: username -> the 6-digit
 * code we email -> a new password. It drives the parent's signal lamps through
 * `onLamp`: amber while typing or checking, red for a wrong code, green once a
 * step is cleared.
 */
export function ForgotFlow({
  initialUsername,
  onBack,
  onDone,
  onLamp,
}: {
  initialUsername: string;
  onBack: () => void;
  onDone: (username: string) => void;
  onLamp: (lamp: Lamp) => void;
}) {
  const uid = useId();
  const [step, setStep] = useState<Step>("user");
  const [username, setUsername] = useState(initialUsername);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false); // typed since the last error
  const [cleared, setCleared] = useState(false); // green beat between steps
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    inputRef.current?.focus();
  }, [step]);
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const typed = step === "user" ? username : step === "code" ? code : password;
  const lamp: Lamp = cleared
    ? "granted"
    : busy
      ? "busy"
      : error && !dirty
        ? "error"
        : typed
          ? "typing"
          : "idle";
  useEffect(() => onLamp(lamp), [lamp, onLamp]);

  /** Run one API call: amber while it runs, then red with a message or a green
   *  beat before `next` moves on. */
  const run = async (call: (signal: AbortSignal) => Promise<void>, next: () => void) => {
    if (busy) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setError(null);
    setDirty(false);
    try {
      await call(controller.signal);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(messageFor(err));
      setBusy(false);
      return;
    }
    setBusy(false);
    setCleared(true);
    await new Promise((r) => setTimeout(r, 700));
    if (controller.signal.aborted) return;
    setCleared(false);
    next();
  };

  const sendCode = (e?: FormEvent) => {
    e?.preventDefault();
    const name = username.trim();
    if (!name) return setError("Enter your username.");
    let hint = "";
    void run(
      async (signal) => {
        hint = await requestResetCode(name, signal);
      },
      () => {
        setSentTo(hint);
        setWait(RESEND_SECONDS);
        setCode("");
        setStep("code");
      },
    );
  };

  const checkCode = (e: FormEvent) => {
    e.preventDefault();
    if (code.length !== 6) return setError("Enter the 6-digit code.");
    void run((signal) => verifyResetCode(username.trim(), code, signal), () => setStep("password"));
  };

  const savePassword = (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters.`);
    void run(
      (signal) => resetPassword(username.trim(), code, password, signal),
      () => onDone(username.trim()),
    );
  };

  const errorBox = error && (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-xl bg-status-critical-muted px-3.5 py-3 text-[13px] text-status-critical"
    >
      <TriangleAlert className="mt-px size-4 shrink-0" aria-hidden />
      <span>{error}</span>
    </div>
  );
  const submit = (label: string, busyLabel: string) => (
    <Button
      type="submit"
      variant="primary"
      size="lg"
      aria-disabled={busy}
      className="h-11 w-full aria-disabled:cursor-wait aria-disabled:opacity-70"
    >
      {busy ? busyLabel : label}
    </Button>
  );
  const border = (bad: boolean) => (bad ? "border-status-critical" : "border-input focus-visible:border-primary");

  return (
    <div>
      <h2 className="text-lg font-semibold tracking-[-0.01em]">
        {step === "password" ? "Choose a new password" : "Reset your password"}
      </h2>

      {step === "user" && (
        <form onSubmit={sendCode} noValidate aria-busy={busy} className="mt-4 flex flex-col gap-4">
          <p className="text-[13px] text-muted-foreground">
            Enter your username (not your email) and we'll email a 6-digit code to the address on your account.
          </p>
          <Field label="Username" id={`${uid}-u`}>
            <input
              ref={inputRef}
              id={`${uid}-u`}
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                setDirty(true);
              }}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={128}
              readOnly={busy}
              className={cn(INPUT, border(!!error && !dirty))}
            />
          </Field>
          {errorBox}
          {submit("Send code", "Sending…")}
        </form>
      )}

      {step === "code" && (
        <form onSubmit={checkCode} noValidate aria-busy={busy} className="mt-4 flex flex-col gap-4">
          <p className="text-[13px] text-muted-foreground" role="status">
            {sentTo
              ? `We sent a 6-digit code to ${sentTo}. It expires in 10 minutes.`
              : null}
          </p>
          <Field label="6-digit code" id={`${uid}-c`}>
            <input
              ref={inputRef}
              id={`${uid}-c`}
              value={code}
              onChange={(e) => {
                setCode(e.target.value.replace(/\D/g, "").slice(0, 6));
                setDirty(true);
              }}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              readOnly={busy}
              placeholder="000000"
              className={cn(INPUT, "text-center font-mono text-xl tracking-[0.5em]", border(!!error && !dirty))}
            />
          </Field>
          {errorBox}
          {submit("Verify code", "Checking…")}
          <button
            type="button"
            disabled={wait > 0 || busy}
            onClick={() => sendCode()}
            className="text-center text-[13px] font-medium text-foreground/80 underline underline-offset-2 hover:text-foreground disabled:cursor-not-allowed disabled:no-underline disabled:opacity-60"
          >
            {wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}
          </button>
        </form>
      )}

      {step === "password" && (
        <form onSubmit={savePassword} noValidate aria-busy={busy} className="mt-4 flex flex-col gap-4">
          <p className="text-[13px] text-muted-foreground">
            Code accepted. Pick a password of at least {MIN_PASSWORD} characters; you'll be signed out
            everywhere else.
          </p>
          <Field label="New password" id={`${uid}-p`}>
            <div className="relative">
              <input
                ref={inputRef}
                id={`${uid}-p`}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setDirty(true);
                }}
                autoComplete="new-password"
                maxLength={256}
                readOnly={busy}
                className={cn(INPUT, "pr-12", border(!!error && !dirty))}
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
          </Field>
          {errorBox}
          {submit("Change password", "Saving…")}
        </form>
      )}

      <button
        type="button"
        onClick={onBack}
        className="mt-5 inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground/80 hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Back to sign in
      </button>
    </div>
  );
}
