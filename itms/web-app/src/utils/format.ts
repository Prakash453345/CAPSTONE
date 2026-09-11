/** Small, dependency-free formatting helpers for operational readouts. */

const timeFmt = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** Wall-clock HH:MM:SS for the top-bar clock. */
export function formatClock(date: Date): string {
  return timeFmt.format(date);
}

/** Compact "3s ago" / "4m ago" / "2h ago" relative label. */
export function formatRelative(from: Date | string, now: Date = new Date()): string {
  const then = typeof from === "string" ? new Date(from) : from;
  const secs = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/** Thousands-separated integer, e.g. 12_480 -> "12,480". */
export function formatCount(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}
