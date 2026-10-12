# Material Design 3 and the Google Maps web UI: values for a map dashboard

Research date: 2026-09-25. Main sources:
- **M3 token source.** m3.material.io renders on the client, so WebFetch returned only the page title. Every M3 value below therefore comes from Google's machine-generated token files:
  - material-web `tokens/versions/latest/sass/*`. The last commit on that folder is 2026-04-06, "chore: update latest tokens to v34", so these are the current, Expressive-era tokens.
  - The androidx Compose Material3 source.
  - The material-components-android Motion.md doc.
- **Google Maps web.** I measured it myself in a browser at 1440x900 on 2026-09-25 (google.com/maps, hl=en), using getBoundingClientRect and getComputedStyle. Those numbers describe the live DOM on that date. They are not a published Google spec.

Token file base URL (abbreviated below as TOK):
https://github.com/material-components/material-web/tree/main/tokens/versions/latest/sass

## Q1. Material 3 motion: easing, duration and springs

### Takeaway
M3 has two sets of cubic-bezier easings, emphasized and standard, each with a decelerate curve for entering and an accelerate curve for exiting. There are 16 duration tokens from 50 to 1000 ms. The 2025 Expressive update adds six spring tokens (fast, default and slow, each in a spatial and an effects variant), and components now use these springs. For CSS, use the beziers. The full emphasized curve is a two-segment path that a single cubic-bezier cannot express.

### Cited findings
- **Easing tokens (material-web `_md-sys-motion.scss`)** — [TOK/_md-sys-motion.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-motion.scss)
  - `easing-standard` = `cubic-bezier(0.2, 0, 0, 1)`
  - `easing-standard-decelerate` = `cubic-bezier(0, 0, 0, 1)`
  - `easing-standard-accelerate` = `cubic-bezier(0.3, 0, 1, 1)`
  - `easing-emphasized-decelerate` = `cubic-bezier(0.05, 0.7, 0.1, 1)`
  - `easing-emphasized-accelerate` = `cubic-bezier(0.3, 0, 0.8, 0.15)`
  - `easing-linear` = `cubic-bezier(0, 0, 1, 1)`
  - Legacy (Material 2) curves:
    - `easing-legacy` = `cubic-bezier(0.4, 0, 0.2, 1)`
    - `easing-legacy-decelerate` = `cubic-bezier(0, 0, 0.2, 1)`
    - `easing-legacy-accelerate` = `cubic-bezier(0.4, 0, 1, 1)`
  - In the CSS token file, `$easing-emphasized` is aliased to `$easing-standard`. The generator comments say the `motion_path` type "is not supported."
- **Full emphasized easing.** Android defines it as the path `M 0,0 C 0.05, 0, 0.133333, 0.06, 0.166666, 0.4 C 0.208333, 0.82, 0.25, 1, 1, 1`. That is two joined cubic segments, and a single CSS cubic-bezier cannot reproduce it. — [MDC-Android Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)
- **When to use each easing** — [MDC-Android Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)
  - Standard is for "utility focused animations that begin and end on screen." Standard decelerate is for utility animations that enter the screen, and standard accelerate is for those that exit.
  - Emphasized is for "common, M3-styled animations that begin and end on screen." Emphasized decelerate is for enter, and emphasized accelerate is for exit.
  - Linear is for "simple, non-stylized motion."
- **Duration tokens (ms)** — [TOK/_md-sys-motion.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-motion.scss); the same values appear as `?attr/motionDuration*` in [Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)

  | Group | 1 | 2 | 3 | 4 |
  |---|---|---|---|---|
  | short | 50 | 100 | 150 | 200 |
  | medium | 250 | 300 | 350 | 400 |
  | long | 450 | 500 | 550 | 600 |
  | extra-long | 700 | 800 | 900 | 1000 |

- **Duration rule.** "Duration should increase as the area/traversal of an animation increases." — [Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)
- **Default durations for transition patterns (Android)** — [Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)
  - Container transform: 450 ms incoming (long1), 300 ms outgoing (medium2), scrim `#52000000` (32% black).
  - Shared axis and fade through: 450 ms.
  - Fade: 100 ms in, 50 ms out, linear.
  - Caveat: that section lists the easing as `cubic-bezier(0.4,0,0.2,1)`. That is the legacy curve, not the current standard curve, so the section is probably stale.
- **Compose bottom sheet animation.** The default is `tween(durationMillis = 300, easing = FastOutSlowInEasing)`. — [androidx SheetDefaults.kt](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/SheetDefaults.kt)
- **Expressive springs.** Damping is a ratio; stiffness is in the Android spring units. — [TOK/_md-sys-motion.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-motion.scss); usage notes from [Motion.md](https://raw.githubusercontent.com/material-components/material-components-android/master/docs/theming/Motion.md)

  | Token | Damping | Stiffness | Use |
  |---|---|---|---|
  | `spring-fast-spatial` | 0.9 | 1400 | Small components (switches, buttons) |
  | `spring-fast-effects` | 1.0 | 3800 | |
  | `spring-default-spatial` | 0.9 | 700 | Partial-screen surfaces (bottom sheet, nav drawer) |
  | `spring-default-effects` | 1.0 | 1600 | |
  | `spring-slow-spatial` | 0.9 | 300 | Full-screen |
  | `spring-slow-effects` | 1.0 | 800 | |

  - Spatial springs move things and may overshoot. Effects springs animate colour and opacity and "should not be overshot."
- **Expressive motion schemes.** There are two:
  - Expressive, the recommended default, has lower damping and noticeable bounce.
  - Standard has higher damping and minimal bounce, and suits "utilitarian applications."
  - Spring values vary by device class (wearable, phone, tablet).
  - Source: [M3 blog, "Start building with M3 Expressive"](https://m3.material.io/blog/building-with-m3-expressive). This is a search-result summary only; the page did not render when fetched.
- **The M3 search bar's expand motion** uses `md-sys-motion.$spring-fast-spatial`. — [TOK/_md-comp-search-bar.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-search-bar.scss)

### Inferences
- For a traffic ops dashboard, the calmer **standard** scheme fits better than the bouncy Expressive default.
- Suggested pairings:
  - Small toggles and chips: `cubic-bezier(0.2,0,0,1)` for 150–200 ms.
  - Side panel or sheet entering: `cubic-bezier(0.05,0.7,0.1,1)` for about 400–500 ms.
  - Exiting: `cubic-bezier(0.3,0,0.8,0.15)` for about 200 ms. Exits run shorter than enters.
- To approximate the springs in the browser, a library such as framer-motion can take stiffness and damping values. Its damping is absolute, not a ratio: damping = ratio × 2√(stiffness × mass). Worked value at mass 1: fast-spatial gives about 67.

### Gaps
- m3.material.io's own guidance pages would not render, so I could not quote them directly. That covers:
  - The emphasized-versus-standard "when to use" matrix.
  - The explicit mapping of durations to surface size, for example which exact token to use for a bottom sheet.
- The per-device spring values mentioned for Expressive are not in the web token file. The file holds one set only.

## Q2. Elevation, tonal surfaces, shape, type scale and colour roles

### Takeaway
- **Elevation:** levels 0–5 are 0, 1, 3, 6, 8 and 12 dp.
- **Surfaces:** instead of tinting surfaces by elevation, M3 now uses five fixed surface-container tones:
  - Light scheme: N100, 96, 94, 92, 90.
  - Dark scheme: N4, 10, 12, 17, 22.
- **Corner radii:** 0, 4, 8, 12, 16, 20, 28, 32, 48 and full.
- **Type:** Roboto by default. Label roles and small or medium titles use weight 500; everything else uses 400.

### Cited findings
- **Elevation (dp)**
  - level0 = 0, level1 = 1, level2 = 3, level3 = 6, level4 = 8, level5 = 12 — [TOK/_md-sys-elevation.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-elevation.scss); identical in [Compose ElevationTokens.kt](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/ElevationTokens.kt)
- **Shape (corner radii)**
  - none 0, extra-small 4px, small 8px, medium 12px, large 16px, large-increased 20px, extra-large 28px, extra-large-increased 32px, extra-extra-large 48px, full 9999px.
  - Partial shapes: `corner-extra-large-top` = 28 28 0 0; `corner-large-start` = 16 0 0 16; `corner-large-end` = 0 16 16 0.
  - The "increased" and "extra-extra-large" steps are Expressive-era additions to the M3 scale.
  - Source: [TOK/_md-sys-shape.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-shape.scss)
- **Type scale** (1rem = 16px) — [TOK/_md-sys-typescale.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-typescale.scss); fonts from [TOK/_md-ref-typeface.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-ref-typeface.scss)

  | Role | Size / line height (px) | Weight | Tracking (rem) |
  |---|---|---|---|
  | display-large | 57/64 | 400 | -0.015625 |
  | display-medium | 45/52 | 400 | 0 |
  | display-small | 36/44 | 400 | 0 |
  | headline-large | 32/40 | 400 | 0 |
  | headline-medium | 28/36 | 400 | 0 |
  | headline-small | 24/32 | 400 | 0 |
  | title-large | 22/28 | 400 | 0 |
  | title-medium | 16/24 | 500 | 0.009375 |
  | title-small | 14/20 | 500 | 0.00625 |
  | body-large | 16/24 | 400 | 0.03125 |
  | body-medium | 14/20 | 400 | 0.015625 |
  | body-small | 12/16 | 400 | 0.025 |
  | label-large | 14/20 | 500 | 0.00625 |
  | label-medium | 12/16 | 500 | 0.03125 |
  | label-small | 11/16 | 500 | 0.03125 |

  - Both the brand and plain typefaces are Roboto. Weights: regular 400, medium 500, bold 700.
  - A separate `_md-sys-typescale-emphasized.scss` file exists for Expressive emphasized styles. I did not read its values.
- **Colour roles, light scheme** (baseline tonal references and the baseline purple hexes) — [TOK/_md-sys-color.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-color.scss) and [_md-ref-palette.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-ref-palette.scss)
  - Primary:
    - primary = P40 `#6750a4`
    - on-primary = P100 `#fff`
    - primary-container = P90 `#eaddff`
    - on-primary-container = P30
  - Surfaces:
    - surface = N98 `#fef7ff`
    - surface-dim = N87 `#ded8e1`
    - surface-bright = N98
    - surface-container-lowest = N100 `#fff`
    - surface-container-low = N96 `#f7f2fa`
    - surface-container = N94 `#f3edf7`
    - surface-container-high = N92 `#ece6f0`
    - surface-container-highest = N90 `#e6e0e9`
  - Text and lines:
    - on-surface = N10 `#1d1b20`
    - on-surface-variant = NV30 `#49454f`
    - outline = NV50 `#79747e`
    - outline-variant = NV80 `#cac4d0`
  - Inverse: inverse-surface = N20, inverse-on-surface = N95.
- **Colour roles, dark scheme** — [TOK/_md-sys-color__dark.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-color__dark.scss)
  - Primary: primary = P80 `#d0bcff`, on-primary = P20, primary-container = P30.
  - Surfaces:
    - surface = N6 `#141218`
    - surface-bright = N24 `#3b383e`
    - surface-container-lowest = N4 `#0f0d13`
    - surface-container-low = N10 `#1d1b20`
    - surface-container = N12 `#211f26`
    - surface-container-high = N17 `#2b2930`
    - surface-container-highest = N22 `#36343b`
  - Lines: outline = NV60, outline-variant = NV30 `#49454f`.
- **State-layer opacities**
  - hover 0.08, focus 0.10, pressed 0.10, dragged 0.16, disabled 0.38.
  - Source: [TOK/_md-sys-state.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-sys-state.scss)
  - Older M3 docs gave focus and pressed as 0.12. The latest tokens say 0.10. I did not verify this against the older docs; it comes from memory.

### Inferences
- Map-overlay panels should use surface-container-low or surface (white or near-white) with an elevation shadow. Popovers and menus should use surface-container.
- `surface-tint` still exists as a token (it equals primary). Current M3 differentiates tonal surfaces through the container roles rather than through tint overlays.

### Gaps
- I could not verify an official table mapping each elevation level to a surface-container role, because m3.material.io would not render.
- The CSS box-shadow recipe for each level is not in the token files. The files store levels only as dp.

## Q3. Component specs

### Takeaway
- The search bar is a 56dp pill at elevation 3.
- Chips are 32dp tall, with 8dp corners and 18dp icons.
- FABs are 40, 56 and 96dp.
- The switch track is 52×32dp.
- Segmented buttons are 40dp tall.
- Snackbars are 48dp tall for one line and 68dp for two, with 4dp corners and elevation 3. They last 4 s (short) or 10 s (long).
- Bottom sheets have a 32×4dp handle, 28dp top corners, 640dp maximum width and 56dp peek.
- Navigation rails are 96dp collapsed (80dp narrow) and 220–360dp expanded.

### Cited findings
- **Search bar** — [TOK/_md-comp-search-bar.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-search-bar.scss)
  - container-height 56px, container-shape full, container-elevation level3.
  - Icon 24px, leading and trailing space 16px, icon-to-label space 16px, avatar 30px in a 48px target.
  - Input text uses body-large (16px).
  - Search view tokens are in a separate file, `_md-comp-search-view.scss`, which I did not read.
- **Chips (assist and filter)** — [TOK/_md-comp-assist-chip.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-assist-chip.scss), [TOK/_md-comp-filter-chip.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-filter-chip.scss)
  - container-height 32px, shape corner-small (8px), icon 18px, label label-large (14px/500).
  - Flat chips have a 1px outline. A selected filter chip has a 0px outline.
  - Elevated chips sit at level1, go to level2 on hover and level4 when dragged.
- **FAB** — [TOK/_md-comp-fab.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-fab.scss), [_md-comp-fab-small.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-fab-small.scss), [_md-comp-fab-large.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-fab-large.scss)
  - Default: 56×56, corner-large 16px, icon 24px.
  - Small: 40×40, corner-medium 12px, icon 24px.
  - Large: 96×96, corner-extra-large 28px, icon 36px.
  - Expressive also has a "medium" FAB file (`_md-comp-fab-medium.scss`), which I did not read.
- **Snackbar**
  - Tokens: single-line height 48px, two-line height 68px, shape extra-small 4px, elevation level3, supporting text body-medium, action label-large, icon 24px. — [TOK/_md-comp-snackbar.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-snackbar.scss)
  - Durations in Compose: Short = 4000 ms, Long = 10000 ms, Indefinite = until dismissed. Accessibility settings can lengthen them. — [androidx SnackbarHost.kt](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/SnackbarHost.kt)
- **Bottom sheet**
  - Tokens: drag handle 32×4px, docked shape extra-large-top (28px top corners), elevation level1 for both standard and modal. — [TOK/_md-comp-sheet-bottom.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-sheet-bottom.scss)
  - Compose defaults: `SheetPeekHeight` 56dp, `SheetMaxWidth` 640dp, positional threshold 56dp, velocity threshold 125dp, drag handle vertical padding 22dp. — [androidx SheetDefaults.kt](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/SheetDefaults.kt)
- **Side sheet**
  - Docked width 256px at full height. Standard docked is level0; modal is level1 with shape large-start (16px on the leading corners). A detached sheet has 16px corners.
  - Source: [TOK/_md-comp-sheet-side.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-sheet-side.scss)
- **Navigation rail (Expressive)**
  - Collapsed: width 96px, narrow variant 80px, top space 44px, item vertical space 4px, level0, no corner shape. — [TOK/_md-comp-nav-rail-collapsed.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-nav-rail-collapsed.scss)
  - Expanded: width 220–360px. The modal expanded rail is level2 with 16px corners. — [TOK/_md-comp-nav-rail-expanded.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-nav-rail-expanded.scss)
  - The older `_md-comp-navigation-rail.scss` (pre-Expressive) is still in the repo. I did not open it. The older M3 rail was 80dp wide, but that figure is from memory and unverified.
- **Switch**
  - Track 52×32px with a 2px outline and full shape.
  - Handle: 16px unselected, 24px selected or with an icon, 28px while pressed. Icon 16px.
  - State layer 40px. Handle elevation level1.
  - Source: [TOK/_md-comp-switch.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-switch.scss)
- **Outlined segmented button**
  - Height 40px, shape full, 1px outline, icon 18px, label label-large.
  - Source: [TOK/_md-comp-outlined-segmented-button.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-outlined-segmented-button.scss)
  - Expressive introduces "button groups" as a successor. That is not verified here.

### Inferences
- A floating map search should be 48–56px tall with a full radius. Maps web uses 48px; M3 specifies 56px.
- Category chips should be 32px tall.
- Map FABs ("my location", layers) should be 40px small FABs.
- Alerts should go in a snackbar, bottom-centre or bottom-leading, lasting 4 s. Use Indefinite when an action is required, such as an emergency acknowledgement.

### Gaps
- I found no source for snackbar placement guidance, the M3 page for chip padding (leading 8/16dp and so on), or multiple bottom-sheet peek heights, because m3.material.io would not render. The chip padding values in older M3 docs are unverified.

## Q4. The Google Maps web UI: layout, fonts and published guidance

### Takeaway
- **Layout** (desktop Maps web, measured):
  - A 72px left rail.
  - A floating search box, 48px tall with a 24px radius, 376px wide.
  - A row of floating 32px pill category chips.
  - A 408px results side panel.
  - 29px square zoom and location buttons, bottom-right, with 8px corners.
- **Fonts:** UI text uses Google Sans Text, falling back to Roboto. Google Sans went open source (OFL) in Dec 2025.
- **Google's published guidance:** Google publishes Places UI Kit, which ships Material-derived `--gmp-mat-*` CSS tokens, and the JS API controls guide.

### Cited findings (measured live at 1440×900 on google.com/maps, 2026-09-25) — [Google Maps](https://www.google.com/maps)
- **Left navigation rail**
  - 72px wide. The Menu button is at the top.
  - "Saved" and "Recents" items are 72×64px each, with labels in Google Sans Text 12px/500. "Get app" sits at the bottom.
- **Search box**
  - Container is 376×48px at x=88 (16px gap after the rail), y=12. Radius 24px (pill), background #fff.
  - Shadow: `rgba(0,0,0,.2) 0 2px 4px 0, rgba(0,0,0,.02) 0 -1px 0 0`.
  - Input font is Google Sans Text 15px/400.
- **Category chips**
  - Each sits in a 48px hit area. The visible chip is 32px tall with a 32px radius (fully rounded) and background #fff.
  - Shadow: `rgba(60,64,67,.3) 0 1px 2px 0, rgba(60,64,67,.15) 0 1px 3px 1px`. This is Google's standard "elevation 1" shadow, built on Google Grey 800 #3c4043.
  - Label is Google Sans Text 14px/20px, weight 500, colour rgb(31,31,31) = #1f1f1f.
  - The row is 8px to the right of the search box (x=501, y=21). A 32px round "Next page" chevron button uses the same shadow.
- **Top right**
  - Google apps button: 40px circle.
  - "Sign in" button: 40px tall, radius 100px, background rgb(11,87,208) = #0b57d0, Google Sans Text 14px/500.
- **Map controls, bottom-right**
  - "Show Your Location" button: 29×29px, radius 8px, white, with the same elevation-1 shadow.
  - Zoom in and zoom out form a stacked 29×29 pair with radii 8 8 0 0 and 0 0 8 8.
  - Street View pegman and "Show imagery" sit at the bottom.
  - The layers/imagery thumbnail is 75×75px, bottom-left.
  - Footer links (Terms, Privacy and so on) are Roboto 10px.
- **Results side panel** (after tapping the "Restaurants" chip)
  - `role=main` and `role=feed` ("Results for Restaurants") are 408px wide, starting at x=72 flush against the rail. A 416px wrapper was also present.
  - Text uses classes named after M3 roles:
    - `fontBodyMedium`: 14/20 400, and a 15/24 variant.
    - `fontBodySmall`: 12/16 400.
    - `fontTitleSmall`: 14/20 500.
    - `fontLabelMedium`: 12/16 500.
  - All of these are in Google Sans Text.
  - The page's body font stack is `Roboto, "Noto Sans … UI", Arial, sans-serif`. UI elements override it with `"Google Sans Text", "Google Sans", Roboto, …`.
- **Fonts, background**
  - Google Sans Text was introduced in 2020, is optimised for small sizes, and is "the standard user interface typeface" across Google services.
  - Google Sans Flex (a variable font) was released under OFL on 2025-11-18. Google Sans was released under OFL on 2025-12-10.
  - Source: [Wikipedia: Product Sans](https://en.wikipedia.org/wiki/Product_Sans). This is a secondary source; there is also a [Google Fonts specimen](https://fonts.google.com/specimen/Google+Sans), which I did not open.
- **Maps JavaScript API controls**
  - Default controls:
    - Map type, top-left.
    - Fullscreen, on by default.
    - Camera control, visible by default.
    - Street View and rotate, bottom-right.
    - Scale, off by default.
  - Positions can be logical (`BLOCK_START_INLINE_END` and similar) or the legacy `TOP_LEFT` and so on.
  - The recommended custom-control CSS is height 40px, `border-radius: 2px`, `box-shadow: 0 1px 4px -1px rgba(0,0,0,0.3)`, `font-family: Roboto, Arial, sans-serif`, font-size 18px, margin 10px. That look is older than the rounded web-app controls measured above.
  - Source: [Maps JS API: Controls](https://developers.google.com/maps/documentation/javascript/controls)
- **Places UI Kit**
  - Prebuilt Place Details, Place Search, Place List and Autocomplete elements that "bring the familiar Google Maps user experience" to your own pages. — [Places UI Kit overview](https://developers.google.com/maps/documentation/javascript/places-ui-kit/overview)
  - The design system is "roughly based on Material Design" with Maps modifications. It adapts to light and dark mode through `color-scheme`. — [Places UI Kit custom styling](https://developers.google.com/maps/documentation/javascript/places-ui-kit/custom-styling)
  - Colour tokens: `--gmp-mat-color-surface`, `-on-surface`, `-on-surface-variant`, `-primary`, `-secondary-container`, `-on-secondary-container`, `-neutral-container`, `-on-neutral-container`, `-outline-decorative`, `-disabled-surface`, `-positive`, `-positive-container`, `-on-positive-container`, `-negative`, `-info`.
  - Font tokens: `--gmp-mat-font-family`, `--gmp-mat-font-display-small`, `-headline-medium`, `-title-small`, `-body-medium`, `-body-small`, `-label-large`, `-label-medium`.
  - The page lists no default values for any of these tokens.
- **Maps on Android** received Material 3 Expressive treatment in September 2025:
  - The action carousel (Directions, Start, Ask, Call, Save, Share) is permanently docked at the bottom.
  - Place-detail fields sit in M3E containers instead of being split by hairline separators.
  - Action buttons are pills.
  - The app still lacks Dynamic Color.
  - Source: [9to5Google, 2025-09-17](https://9to5google.com/2025/09/17/google-maps-m3-expressive/)

### Inferences
- The web Maps UI does not follow stock M3 tokens exactly:
  - Search is 48px, not 56.
  - Chips are fully rounded, not 8px.
  - Map controls are 29px squares with 8px corners.
  - The panel is 408px, versus a 256px M3 side sheet.
  - Shadows use Google's #3c4043-based elevation, not M3 dp levels.
- For a dashboard that should "feel like Google Maps," the measured Maps values are the better target. Stock M3 values are the better target for "feel like Material."
- The primary blue #0b57d0 matches the Google Material 3 "GM3" baseline blue, and #1f1f1f is its on-surface. This is inferred and not verified against a token source.

### Gaps
- **Mobile web bottom sheet:** peek heights and handle not measured. On phone widths google.com/maps pushes the app; I did not measure it.
- **Controls:** I did not measure the dark theme or satellite mode.
- **Official UI guidelines:** I found no official Google Maps UI design guideline document (as opposed to API docs).
- **Cloud-based map styling:** I did not research its best-practices page (for example, reducing POI density for data overlays).
- **Side panel animation:** the open and close curve was not measured.

## Q5. Accessibility: touch targets and contrast

### Takeaway
M3 and Compose reserve a minimum interactive size of 48×48dp. Google Maps web meets this through 48px hit areas around its 32px chips, and a 48px search height.

### Cited findings
- Compose's `minimumInteractiveComponentSize` "reserves at least 48.dp in size to disambiguate touch interactions." Its default touch target is 48dp. — [androidx InteractiveComponentSize.kt](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/InteractiveComponentSize.kt)
- The search bar's avatar target is 48px — [TOK/_md-comp-search-bar.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-search-bar.scss); the switch state layer is 40px — [TOK/_md-comp-switch.scss](https://github.com/material-components/material-web/blob/main/tokens/versions/latest/sass/_md-comp-switch.scss)
- On Maps web, the chip buttons measure 48px tall around a 32px visual chip. The zoom buttons are only 29×29px, so they fall below 48 on desktop. — [Google Maps](https://www.google.com/maps) (measured)

### Inferences
- Use 32px visual chips inside 48px hit areas. The 29px Maps-style controls are fine on desktop but should grow to 40–48px on touch.

### Gaps
- I could not open M3's contrast guidance page, so I have no citation for its 4.5:1 text and 3:1 non-text figures. These are WCAG 2.x AA values and are unverified against M3's own page.
