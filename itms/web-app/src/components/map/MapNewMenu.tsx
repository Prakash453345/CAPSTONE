import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Ambulance, Plus, TriangleAlert, X } from "lucide-react";
import { MAP_CHIP, MAP_CHIP_ACTIVE } from "@/components/map/mapChrome";
import { EASE_OUT } from "@/components/console/motion";
import { useDismiss } from "@/components/console/hooks";
import { CREW_TYPES, selectSelectedRequest, useEmergencyStore } from "@/store/emergencyStore";
import { useMapStore } from "@/store/mapStore";
import { cn } from "@/utils/cn";

/**
 * The map's single entry point for starting something: report a disruption
 * or dispatch a unit. While one of those flows is open the chip becomes its
 * cancel button, so there is never more than one call to action on the map.
 */
export function MapNewMenu({ onCancelAnomaly }: { onCancelAnomaly: () => void }) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  useDismiss(open, () => setOpen(false), [anchor, menu]);
  // the map's action stack scrolls, so the menu is portalled and pinned to the chip
  useLayoutEffect(() => {
    if (!open || !anchor.current) return;
    const r = anchor.current.getBoundingClientRect();
    setPos({ top: r.bottom + 8, left: r.left });
  }, [open]);
  const interactionMode = useMapStore((s) => s.interactionMode);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const draft = useEmergencyStore((s) => s.draft);
  const selected = useEmergencyStore(selectSelectedRequest);
  const startDraft = useEmergencyStore((s) => s.startDraft);

  const creating = interactionMode === "create-anomaly";
  // the dispatch panel carries its own Cancel; one is enough
  if (draft) return null;
  if (creating) {
    return (
      <button type="button" className={cn(MAP_CHIP, MAP_CHIP_ACTIVE)} onClick={onCancelAnomaly}>
        <X />
        Cancel
      </button>
    );
  }

  const items = [
    {
      label: "Report a disruption",
      hint: "An accident, breakdown or blocked lane",
      icon: TriangleAlert,
      run: () => setInteractionMode("create-anomaly"),
    },
    {
      label: "Dispatch a unit",
      hint: "Send the nearest ambulance, police or fire crew",
      icon: Ambulance,
      run: () => startDraft(CREW_TYPES[0]!),
    },
  ];

  return (
    <div ref={anchor} className="pointer-events-auto relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(MAP_CHIP, (open || selected) && MAP_CHIP_ACTIVE)}
        onClick={() => setOpen((o) => !o)}
      >
        <Plus />
        New
      </button>
      {createPortal(
      <AnimatePresence>
        {open && (
          <motion.div
            ref={menu}
            role="menu"
            style={{ top: pos.top, left: pos.left }}
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.16, ease: EASE_OUT }}
            className="fixed z-[45] w-[272px] origin-top-left rounded-2xl bg-surface-raised p-1.5 shadow-elevation-3"
          >
            {items.map((it) => (
              <button
                key={it.label}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  it.run();
                }}
                className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-muted"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
                  <it.icon className="size-4" strokeWidth={1.9} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground">{it.label}</span>
                  <span className="block text-[12px] text-muted-foreground">{it.hint}</span>
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>,
      document.body,
      )}
    </div>
  );
}
