import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/utils/cn";

/**
 * The floating cards on the console map, in one style so they read as one
 * product: Apple Maps' place sheets (large radius, one soft shadow, no inner
 * borders, grouped rows on a sunken fill) with Google Maps' compact density.
 * Colours come from the theme tokens only, so every card works in light and
 * dark mode alike.
 */
export function Sheet({
  title,
  icon,
  subtitle,
  onClose,
  closeLabel = "Close",
  width = "w-[344px]",
  children,
  footer,
}: {
  title: ReactNode;
  icon?: ReactNode;
  subtitle?: ReactNode;
  onClose?: () => void;
  closeLabel?: string;
  width?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "pointer-events-auto flex max-h-[calc(100vh-9rem)] max-w-full origin-top-left animate-sheet-in flex-col overflow-hidden rounded-[20px] bg-surface-raised shadow-elevation-3",
        width,
      )}
    >
      <header className="flex items-start gap-3 px-4 pb-2 pt-4">
        {icon && (
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-muted text-primary [&_svg]:size-[18px]">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="line-clamp-2 text-[17px] font-semibold leading-tight tracking-[-0.01em]">{title}</h2>
          {subtitle && <p className="mt-0.5 line-clamp-2 text-[13px] text-muted-foreground">{subtitle}</p>}
        </div>
        {onClose && (
          <button
            type="button"
            aria-label={closeLabel}
            onClick={onClose}
            className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground transition-colors hover:text-foreground [&_svg]:size-4"
          >
            <X />
          </button>
        )}
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 pb-4 pt-2">{children}</div>
      {footer && <footer className="space-y-2 border-t border-border/70 px-4 py-3">{footer}</footer>}
    </section>
  );
}

/** A small heading over a group of rows, like the grey captions in iOS lists. */
export function SectionLabel({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-1.5 flex items-baseline justify-between gap-2 px-1">
      <h3 className="text-[12px] font-medium text-muted-foreground">{children}</h3>
      {aside && <span className="text-[12px] text-muted-foreground">{aside}</span>}
    </div>
  );
}

/** Rows grouped on one sunken card, separated by hairlines. */
export function Group({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("divide-y divide-border/70 overflow-hidden rounded-2xl bg-surface-fill", className)}>
      {children}
    </div>
  );
}

/** An iOS segmented control: a sunken track with the chosen segment raised. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { id: T; label: string; icon?: ReactNode }[];
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1 rounded-[12px] bg-surface-fill p-1">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.id)}
            className={cn(
              "flex h-9 flex-1 items-center justify-center gap-1.5 rounded-[9px] text-[13px] font-medium transition-[background-color,color,box-shadow] duration-150 [&_svg]:size-4",
              on
                ? "bg-surface-raised text-foreground shadow-elevation-1"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A pill to pick one of several values (types, severities). */
export function Pill({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-8 items-center justify-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors duration-150 [&_svg]:size-3.5",
        active
          ? "bg-primary text-primary-foreground"
          : "bg-surface-fill text-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

/** Something went wrong, said in a sentence, in a colour that reads in both themes. */
export function InlineError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-xl bg-status-critical-muted px-3 py-2 text-[13px] text-status-critical">
      {children}
    </p>
  );
}

/** The one main action of a sheet. */
export function PrimaryButton({
  children,
  disabled,
  onClick,
  tone = "primary",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
  tone?: "primary" | "critical";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-11 w-full items-center justify-center gap-2 rounded-[14px] text-[15px] font-semibold transition-[filter,opacity] duration-150 hover:brightness-105 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:size-[18px]",
        tone === "critical" ? "bg-status-critical text-white" : "bg-primary text-primary-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** A quieter action: tinted text on the sunken fill. */
export function SecondaryButton({
  children,
  disabled,
  onClick,
  tone,
  title,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
  tone?: "critical";
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-10 w-full flex-1 items-center justify-center gap-1.5 rounded-[12px] bg-surface-fill text-[14px] font-medium transition-colors duration-150 hover:bg-muted disabled:opacity-50 [&_svg]:size-4",
        tone === "critical" ? "text-status-critical" : "text-primary",
      )}
    >
      {children}
    </button>
  );
}
