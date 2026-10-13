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

/** Event data for camera moves the operator asked for through an on-map
 *  control (zoom buttons, 3D, compass). Mouse, touch and keyboard gestures
 *  already carry an `originalEvent`; these don't, so they say so explicitly.
 *  `FollowCamera` pauses on either and on nothing else. */
export const USER_GESTURE = { userGesture: true } as const;
