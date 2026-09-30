import {
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { AnimatePresence, animate, motion, useReducedMotion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/utils/cn";
import { EASE_OUT } from "@/components/console/motion";
import { useDismiss, useIndicator } from "@/components/console/hooks";
import { TONE_BG, TONE_DOT, TONE_TEXT, type Tone } from "@/components/console/tone";


/**
 * The console's building blocks. Pages compose these instead of styling
 * cards ad hoc, so spacing, type and motion stay consistent everywhere.
 */


// ------------------------------------------------------------ surfaces

export function Panel({
  children,
  className,
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "aside" | "article";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag className={cn("rounded-2xl bg-surface shadow-elevation-1", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function PanelHeader({
  title,
  subtitle,
  actions,
  className,
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <header className={cn("flex items-start justify-between gap-3 px-5 pb-3 pt-4", className)}>
      <div className="min-w-0">
        <h2 id={id} className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {title}
        </h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </header>
  );
}

/** A content page's title row: title, one line of context, and actions on the right. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

// ------------------------------------------------------------ controls

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className,
  icon: Icon,
  ...rest
}: {
  children?: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: LucideIcon;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition-[background-color,color,box-shadow,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        size === "md" ? "h-9 px-3.5 text-[13.5px]" : "h-8 px-3 text-[13px]",
        variant === "primary" && "bg-primary text-primary-foreground shadow-elevation-1 hover:bg-primary/90",
        variant === "secondary" && "bg-surface text-foreground shadow-elevation-1 hover:bg-muted",
        variant === "ghost" && "text-muted-foreground hover:bg-muted hover:text-foreground",
        variant === "danger" && "bg-status-critical-muted text-status-critical hover:bg-status-critical/15",
        className,
      )}
      {...rest}
    >
      {Icon && <Icon className="size-4 shrink-0" strokeWidth={1.9} />}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  icon: Icon,
  className,
  active,
  ...rest
}: {
  label: string;
  icon: LucideIcon;
  active?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "grid size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground",
        active && "bg-muted text-foreground",
        className,
      )}
      {...rest}
    >
      <Icon className="size-[18px]" strokeWidth={1.8} />
    </button>
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
}

/** A segmented control whose selection pill glides between options. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegmentOption<T>[];
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const pill = useIndicator(root, '[aria-checked="true"]', [value, options.length]);
  return (
    <div
      ref={root}
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn("relative isolate inline-flex items-center rounded-xl bg-muted p-1", className)}
    >
      <span aria-hidden className="absolute left-0 top-0 -z-10 rounded-lg bg-surface shadow-elevation-1" style={pill} />
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={opt.label}
            onClick={() => onChange(opt.value)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors duration-150",
              size === "md" ? "h-8 px-3 text-[13px]" : "h-7 px-2.5 text-xs",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {opt.icon && <opt.icon className="size-3.5" strokeWidth={2} />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-border bg-surface px-1 font-sans text-[11px] font-medium text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={cn(
        "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full p-0.5 transition-colors duration-200",
        checked ? "bg-primary" : "bg-input",
      )}
    >
      <span
        className={cn(
          "size-5 rounded-full bg-white shadow-elevation-1 transition-transform duration-300 ease-[cubic-bezier(.22,1,.36,1)]",
          checked && "translate-x-4",
        )}
      />
    </button>
  );
}

// ------------------------------------------------------------ popover

export function Popover({
  open,
  onClose,
  anchor,
  children,
  align = "end",
  className,
  label,
}: {
  open: boolean;
  onClose: () => void;
  anchor: RefObject<HTMLElement | null>;
  children: ReactNode;
  align?: "start" | "end";
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(open, onClose, [ref, anchor]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={ref}
          role="dialog"
          aria-label={label}
          initial={{ opacity: 0, y: -6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.98 }}
          transition={{ duration: 0.18, ease: EASE_OUT }}
          className={cn(
            "absolute top-[calc(100%+8px)] z-50 origin-top rounded-2xl bg-surface-raised p-2 shadow-elevation-3",
            align === "end" ? "right-0 origin-top-right" : "left-0 origin-top-left",
            className,
          )}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ------------------------------------------------------------ data display

/** A number that glides to its new value instead of snapping. */
export function AnimatedNumber({
  value,
  format = (v) => Math.round(v).toLocaleString(),
  className,
}: {
  value: number | null;
  format?: (v: number) => string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef<number | null>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (value === null) {
      el.textContent = "–";
      last.current = null;
      return;
    }
    const from = last.current ?? value;
    last.current = value;
    if (reduce || from === value) {
      el.textContent = format(value);
      return;
    }
    const c = animate(from, value, {
      duration: 0.8,
      ease: EASE_OUT,
      onUpdate: (v) => (el.textContent = format(v)),
    });
    return () => c.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <span ref={ref} className={cn("tabular", className)}>
      {value === null ? "–" : format(value)}
    </span>
  );
}

export function Pill({ tone = "neutral", children, dot = false, className }: { tone?: Tone; children: ReactNode; dot?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-medium",
        TONE_BG[tone],
        TONE_TEXT[tone],
        className,
      )}
    >
      {dot && <span className={cn("size-1.5 rounded-full", TONE_DOT[tone])} />}
      {children}
    </span>
  );
}

export function Dot({ tone = "neutral", pulse = false, className }: { tone?: Tone; pulse?: boolean; className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)}>
      {pulse && <span className={cn("absolute inset-0 animate-ping-ring rounded-full opacity-60", TONE_DOT[tone])} />}
      <span className={cn("relative size-2 rounded-full", TONE_DOT[tone])} />
    </span>
  );
}

/** A thin horizontal meter, animated to its value. */
export function Meter({ value, tone = "info", className }: { value: number; tone?: Tone; className?: string }) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-muted", className)}>
      <motion.div
        className={cn("h-full rounded-full", TONE_DOT[tone])}
        initial={false}
        animate={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        transition={{ duration: 0.7, ease: EASE_OUT }}
      />
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-10 text-center", className)}>
      <span className="grid size-11 place-items-center rounded-2xl bg-muted text-muted-foreground">
        <Icon className="size-5" strokeWidth={1.8} />
      </span>
      <p className="mt-3 text-sm font-medium text-foreground">{title}</p>
      {body && <p className="mt-1 max-w-[30ch] text-[13px] leading-relaxed text-muted-foreground">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

