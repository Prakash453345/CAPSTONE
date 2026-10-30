import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/utils/cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none tracking-wide",
  {
    variants: {
      tone: {
        neutral: "border-border bg-muted text-muted-foreground",
        ok: "border-transparent bg-status-ok-muted text-status-ok",
        warn: "border-transparent bg-status-warn-muted text-status-warn",
        critical: "border-transparent bg-status-critical-muted text-status-critical",
        info: "border-transparent bg-status-info-muted text-status-info",
        primary: "border-transparent bg-primary-muted text-primary",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
