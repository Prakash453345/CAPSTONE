/**
 * Shared classes for the floating controls on the map, measured from Google
 * Maps: category chips are 32px pills with Material elevation-1 that turn
 * tonal blue while active.
 */
export const MAP_CHIP =
  "pointer-events-auto flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-surface-raised px-3 text-[13px] font-medium text-foreground shadow-elevation-1 transition-[background-color,box-shadow] duration-150 ease-out hover:bg-muted hover:shadow-elevation-2 [&_svg]:size-4 [&_svg]:text-muted-foreground";

export const MAP_CHIP_ACTIVE =
  "bg-primary-muted text-primary hover:bg-primary-muted [&_svg]:text-primary";

/** Google blue, used for the searched-road highlight and selection accents. */
export const HIGHLIGHT_BLUE = "#1a73e8";
