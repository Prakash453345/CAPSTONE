import { cn } from "@/utils/cn";

/**
 * The TRAFFIX mark — a crosshair standing in for an intersection. Shared by
 * `SideNav` (collapsed-rail size) and `LandingPage` (hero size) so there's
 * one definition of "what the brand looks like", not two SVGs to keep in
 * sync.
 */
export function BrandMark({ size = "md" }: { size?: "md" | "lg" }) {
  const box = size === "lg" ? "size-16 rounded-2xl" : "size-8 rounded-lg";
  const icon = size === "lg" ? 32 : 16;
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center border border-primary/30 bg-primary-muted/40",
        box,
      )}
    >
      <svg width={icon} height={icon} viewBox="0 0 32 32" fill="none" aria-hidden>
        <path
          d="M16 4v24M4 16h24"
          stroke="hsl(var(--primary))"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle
          cx="16"
          cy="16"
          r="3.4"
          fill="hsl(var(--background))"
          stroke="hsl(var(--primary))"
          strokeWidth="2.5"
        />
      </svg>
    </span>
  );
}
