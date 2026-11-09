export const INPUT =
  "h-11 w-full rounded-xl border bg-surface px-3.5 text-[15px] text-foreground outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground/70 focus-visible:rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring read-only:opacity-70";

export type Lamp = "idle" | "typing" | "busy" | "granted" | "error";

export const LAMP_TEXT: Record<Lamp, string> = {
  idle: "Ready",
  typing: "Typing…",
  busy: "Checking…",
  granted: "Access granted",
  error: "Access denied",
};

