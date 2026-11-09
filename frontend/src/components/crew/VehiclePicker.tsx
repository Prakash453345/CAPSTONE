import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Dot } from "@/components/console/kit";
import { CREW_TYPES } from "@/store/emergencyStore";
import { statusTag, type UnitOption, type UnitStatus } from "@/crew/useMission";
import { cn } from "@/utils/cn";

const GROUPS: { status: UnitStatus; label: string; tone: "ok" | "warn" | "neutral" }[] = [
  { status: "corridor", label: "On green corridor", tone: "ok" },
  { status: "dispatched", label: "Dispatched", tone: "warn" },
  { status: "available", label: "Available", tone: "neutral" },
];

type Filter = "active" | "available" | "all";

const matches = (f: Filter, u: UnitOption) => f === "all" || (f === "available" ? u.status === "available" : u.status !== "available");

/** A vehicle picker that shows status at a glance (the native <select> can't be styled). */
export function VehiclePicker({ units, unitId, onUnit }: { units: UnitOption[]; unitId: string | null; onUnit: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>("active");
  const [kind, setKind] = useState<string>("all");
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const current = units.find((u) => u.id === unitId);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const activeCount = units.filter((u) => matches("active", u)).length;
  // With nothing active, an "Active" list would be empty: show everyone instead.
  const effective: Filter = filter === "active" && !activeCount ? "all" : filter;
  const q = query.trim().toLowerCase();
  const shown = units.filter((u) => matches(effective, u) && (kind === "all" || u.kind === kind) && (!q || u.name.toLowerCase().includes(q)));
  const chips: { id: Filter; label: string; n: number }[] = [
    { id: "active", label: "Active", n: activeCount },
    { id: "available", label: "Available", n: units.length - activeCount },
    { id: "all", label: "All", n: units.length },
  ];

  const kinds = CREW_TYPES.filter((t) => units.some((u) => u.kind === t.kind));
  const kindLabel = (k?: string) => CREW_TYPES.find((t) => t.kind === k)?.label;

  const tone = (s: UnitStatus) => GROUPS.find((g) => g.status === s)!.tone;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        id="crew-unit"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          setQuery("");
          setOpen((o) => !o);
        }}
        className="flex h-12 w-full items-center gap-3 rounded-xl border border-input bg-surface px-3 text-left outline-none transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring"
      >
        {current ? <Dot tone={tone(current.status)} pulse={current.status === "corridor"} /> : <span className="size-2" />}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-semibold leading-tight">{current?.name ?? (units.length ? "Choose a vehicle…" : "No unit has had a call yet")}</span>
          {current && <span className="block truncate text-[12px] leading-tight text-muted-foreground">{statusTag(current)}</span>}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>

      {open && (
        <div role="listbox" aria-label="Vehicle" className="absolute inset-x-0 top-full z-50 mt-2 max-h-[60vh] overflow-y-auto rounded-2xl border border-border bg-surface-raised p-1.5 shadow-elevation-3">
          <div className="sticky top-0 z-10 -mx-1.5 -mt-1.5 space-y-2 bg-surface-raised px-3 pb-2 pt-3">
            <label className="flex h-9 items-center gap-2 rounded-lg bg-muted px-2.5 text-muted-foreground focus-within:ring-2 focus-within:ring-ring">
              <Search className="size-4 shrink-0" aria-hidden />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search vehicles"
                aria-label="Search vehicles"
                className="min-w-0 flex-1 bg-transparent text-[14px] text-foreground outline-none placeholder:text-muted-foreground"
              />
            </label>
            <div className="flex gap-1.5" role="group" aria-label="Filter vehicles">
              {chips.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={effective === c.id}
                  onClick={() => setFilter(c.id)}
                  className={cn("h-7 rounded-full px-3 text-[12.5px] font-medium transition-colors", effective === c.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}
                >
                  {c.label} · {c.n}
                </button>
              ))}
            </div>
            {kinds.length > 1 && (
              <div className="flex gap-1.5" role="group" aria-label="Vehicle type">
                {[{ kind: "all", label: "All types" }, ...kinds].map((t) => (
                  <button
                    key={t.kind}
                    type="button"
                    aria-pressed={kind === t.kind}
                    onClick={() => setKind(t.kind)}
                    className={cn("h-7 rounded-full border px-3 text-[12.5px] font-medium transition-colors", kind === t.kind ? "border-foreground/40 bg-muted text-foreground" : "border-border text-muted-foreground hover:text-foreground")}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          {!shown.length && <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">No vehicles match.</p>}
          {GROUPS.map((g) => {
            const group = shown.filter((u) => u.status === g.status).sort((a, b) => (a.kind ?? "").localeCompare(b.kind ?? "") || a.name.localeCompare(b.name, undefined, { numeric: true }));
            if (!group.length) return null;
            return (
              <div key={g.status} role="group" aria-label={g.label}>
                <div className="px-2.5 pb-1 pt-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {g.label} · {group.length}
                </div>
                {group.map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    role="option"
                    aria-selected={u.id === unitId}
                    onClick={() => {
                      onUnit(u.id);
                      setOpen(false);
                    }}
                    className={cn("flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none", u.id === unitId && "bg-muted/60")}
                  >
                    <Dot tone={g.tone} pulse={u.status === "corridor"} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-medium">{u.name}</span>
                      {u.status !== "available" && <span className="block truncate text-[12px] text-muted-foreground">{statusTag(u)}</span>}
                    </span>
                    {kind === "all" && kindLabel(u.kind) && <span className="shrink-0 text-[11.5px] text-muted-foreground">{kindLabel(u.kind)}</span>}
                    {u.id === unitId && <Check className="size-4 shrink-0 text-primary" aria-hidden />}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
