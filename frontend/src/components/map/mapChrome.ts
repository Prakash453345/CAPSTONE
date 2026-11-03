/**
 * Shared classes for the floating controls on the map, in Apple Maps' glass:
 * 32px capsules of frosted material that fill with system blue while active.
 */
export const MAP_CHIP =
  "glass pointer-events-auto flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold tracking-[-0.01em] text-foreground glass-hover transition-colors duration-150 ease-out [&_svg]:size-4 [&_svg]:text-muted-foreground";

export const MAP_CHIP_ACTIVE =
  "bg-system-blue text-white hover:bg-system-blue [&_svg]:text-white";

/** Google blue, used for the searched-road highlight and selection accents. */
export const HIGHLIGHT_BLUE = "#1a73e8";

/** Event data for camera moves the operator asked for through an on-map
 *  control (zoom buttons, 3D, compass). Mouse, touch and keyboard gestures
 *  already carry an `originalEvent`; these don't, so they say so explicitly.
 *  `FollowCamera` pauses on either and on nothing else. */
export const USER_GESTURE = { userGesture: true } as const;
