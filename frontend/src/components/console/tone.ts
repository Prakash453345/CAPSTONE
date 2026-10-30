/** Status tones and the utility classes for each. */

export type Tone = "ok" | "warn" | "critical" | "info" | "neutral";

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-status-ok",
  warn: "text-status-warn",
  critical: "text-status-critical",
  info: "text-primary",
  neutral: "text-muted-foreground",
};
export const TONE_BG: Record<Tone, string> = {
  ok: "bg-status-ok-muted",
  warn: "bg-status-warn-muted",
  critical: "bg-status-critical-muted",
  info: "bg-primary-muted",
  neutral: "bg-muted",
};
export const TONE_DOT: Record<Tone, string> = {
  ok: "bg-status-ok",
  warn: "bg-status-warn",
  critical: "bg-status-critical",
  info: "bg-primary",
  neutral: "bg-muted-foreground/60",
};

export function toneText(t: Tone) {
  return TONE_TEXT[t];
}
export function toneBg(t: Tone) {
  return TONE_BG[t];
}
