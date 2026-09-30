# Apple HIG + MapKit JS for a map-centric web dashboard (React + Tailwind + MapLibre)

Research date: 2026-09-25. Method: Apple HIG pages were read through the JSON data endpoint (`developer.apple.com/tutorials/data/design/human-interface-guidelines/<page>.json`) because the HTML pages are rendered on the client. The links below point to the human-readable HIG URLs that match each JSON page. An automated fetch tool summarized each page, so wording may be paraphrased. The numbers match what the tool extracted.

---

## 1. HIG "Maps": controls, annotations, overlays, clutter, selection/callouts, clustering, emphasis, placement

### Takeaway
Apple's map guidance fits on one page and is minimal. Keep the map fully interactive and free of clutter. Choose a **muted emphasis** basemap when your own data has to stand out. Cluster overlapping points. Make the selected item visually distinct. Show details in a callout or a sheet that never hides the selected spot. Give floating controls enough contrast through a thin stroke, a light shadow, or a blend mode. Liquid Glass did not add any map-specific rules.

### Cited Findings
- "Make your map interactive": people expect to zoom and pan, and noninteractive elements that cover the map break those expectations — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- There are two **emphasis styles**. *Default* uses fully saturated colors and matches the Maps app. *Muted* is desaturated, "great when you have information-rich content that needs to stand out against the map" (`MKStandardMapConfiguration.EmphasisStyle`) — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Help people find places by combining search with category filtering — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- "Clearly identify elements that people select": use distinct styling "like an outline and color variation" — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- "Cluster overlapping points of interest to improve map legibility". One pin stands for several nearby points, and the cluster expands as people zoom in — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Keep the Apple logo and legal link visible. Pad them **7 pt on the sides and 10 pt above and below**. Keep them fixed to the map rather than moving with your UI. If your UI moves, such as a sheet, place them **10 pt above the lowest resting position** of the moving elements. They are hidden on maps smaller than **200×100 px** — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Annotations should match your app's visual style. The default marker is a red tint with a white pin glyph. Glyph text should be **2–3 characters** — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Make standard map features (POIs, territories, physical features) independently selectable when you attach custom information to them (`MKMapFeatureOptions`) — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- There are two overlay levels. **Above roads** is the default: it sits above roads but below buildings and trees, so the context still shows. **Above labels** hides everything beneath it and suits fully abstracted content or hiding irrelevant areas (`MKOverlayLevel`) — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- "Make sure there's enough contrast between custom controls and the map. Consider using a thin stroke, light drop shadow, or blend modes" — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Place cards come in several presentation styles: automatic (based on map size), **full callout** (large and detailed), **compact callout** (small), **caption** ("Open in Apple Maps" link), and **sheet**. A full callout is a popover on iPadOS and macOS and a sheet on iOS — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Choose the place card style to suit the map. Use compact callouts on space-constrained maps with many annotations. Set a minimum width for full callouts. Don't repeat information the app already shows. "Keep the location on your map visible when displaying a place card": set an offset and point the card at the location (`selectionAccessoryOffset`) — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- Indoor maps: add detail progressively as the user zooms. Combine color with icons to tell area types apart. Dim noninteractive surrounding areas and give them a distinct color. Limit scrolling outside the venue. "Don't replicate Apple Maps" and match your own app's style instead — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- The page was last substantively updated on **December 18, 2024** (place cards added). The fetch found no map-specific Liquid Glass changes — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)

### Inferences
- For a traffic dashboard, use a **muted/desaturated basemap** so congestion colors, incidents and emergency routes stand out. This is Apple's own recommendation for data-dense maps. In MapLibre, lower the saturation of road, landuse and POI colors in the style JSON.
- Selection state = outline + color change (for example a white halo ring and a darker fill) rather than only a size change.
- Keep attribution fixed at the map corner with about 7 px / 10 px padding. Move it up when a bottom sheet rises, to 10 px above the sheet's lowest detent.
- Use "above roads" for congestion segments so labels and buildings stay readable. Reserve "above labels" for masking out-of-area regions.

### Gaps
- The HIG Maps page gives no pixel values for control size or placement beyond the logo padding. Control placement is covered only generally, through Liquid Glass layering and hit-target rules.
- I found no HIG guidance on real-time or animated data on maps, such as traffic flow or moving vehicles.

---

## 2. Sheets, Materials, and Liquid Glass (2025)

### Takeaway
Sheets have **medium (about half height) and large** detents. Resizable sheets **must** have a grabber, which can also be tapped to cycle through detents. Liquid Glass (announced June 9, 2025) is a translucent, refracting material reserved for the **controls/navigation layer that floats above content**. It should never be used in the content layer itself, and it should be used sparingly. Under Liquid Glass, half sheets are **inset from the screen edges** with larger corner radii, and they turn **more opaque when expanded to full height**. Treat everything in this section as a 2025 change unless it says otherwise.

### Cited Findings
**Sheets**
- A sheet helps people perform "a scoped task closely related to their current context" — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Detents: **large** (full height, always supported) and **medium** (about half height). A sheet with only the medium detent cannot expand. Custom detents are allowed (`UISheetPresentationController.detents`) — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Offer the medium detent for progressive disclosure, when the most relevant items fit at half height. Skip it when content only makes sense at full height, as with Mail and Messages compose — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- The grabber is required on resizable sheets. It signals that the sheet can be resized by dragging, and tapping it cycles through detents. It works with VoiceOver (`prefersGrabberVisible`) — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- A sheet expands when its content is scrolled or its grabber is dragged — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- iOS and iPadOS sheets can be **nonmodal**, which lets people keep working in the parent view. The Notes format sheet is the example. This is the pattern Apple Maps' persistent sheet relies on — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Show only one sheet at a time. Put Cancel on the leading edge and Done on the trailing edge. Never show Done alone, and never show Cancel, Done and Back together — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Choose another presentation in these cases: full-screen modal for complex or long flows. On macOS, use a **panel** when people "repeatedly provide input and observe results" — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Place cards appear as a popover callout on iPad and Mac but as a sheet on iOS — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)
- The Sheets page was last updated **March 24, 2026** (button placement) — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)

**Liquid Glass (NEW, 2025)**
- Announced **June 9, 2025** for iOS 26, iPadOS 26, macOS Tahoe 26, watchOS 26 and tvOS 26. It is a translucent material that "reflects and refracts" its surroundings, transforms dynamically, adapts between light and dark, and renders specular highlights in real time. It applies to buttons, switches, sliders, tab bars and sidebars — [Apple Newsroom](https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/)
- Liquid Glass is "a dynamic material for controls and navigation elements" that "floats above the content layer" and lets content scroll and show through underneath — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- "Don't use Liquid Glass in the content layer." Use standard materials for backgrounds instead. The exception is transient controls such as sliders and toggles, which take on glass while active — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- "Use Liquid Glass effects sparingly." Limit it to the most important custom functional elements — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- There are two variants. **Regular** is the default and blurs and adjusts the luminosity of what is behind it; use it for text-heavy items such as alerts, sidebars and popovers. **Clear** is highly translucent and meant only over visually rich backgrounds such as photos and video. Over bright content, clear glass needs a **dark dimming layer at 35% opacity** — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- Controls sit in "a distinct functional layer above the content layer". Corner shapes are **concentric**: the hardware shape determines the radii of nested controls, sheets and popovers (`ConcentricRectangle`) — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- A **scroll edge effect** obscures content that scrolls under bars so controls stay legible — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- "Reduce your use of custom backgrounds in controls and navigation elements" because they interfere with the glass — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- Tab bars can minimize on scroll down (`tabBarMinimizeBehavior(.onScrollDown)`) — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- Sheets: "Half sheets are inset from the edge of the display to allow content to peek through". "When a half sheet expands to full height, it transitions to a more opaque appearance". Sheets have an "increased corner radius" — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- Users can pick a preferred Liquid Glass look, or turn on Reduce Transparency or Reduce Motion. Standard components adapt automatically, but custom ones must be tested — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- Liquid Glass responds more strongly to direct touch and more subtly to trackpad input (HIG change noted on **September 9, 2025**) — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- The Adopting Liquid Glass doc gives no map-specific guidance — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)

**Standard materials (pre-2025 and still current)**
- Four thicknesses. `ultraThin` is mostly translucent. `thin` is more translucent than opaque and suits overlays. `regular` is somewhat translucent and suits sidebars and sections. `thick` is more opaque than translucent. Thicker materials give better text contrast, and thinner ones keep more context visible — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- Put **vibrant** system colors on materials. Labels have four levels: label, secondary, tertiary and quaternary (avoid quaternary on thin or ultraThin). Fills have three: fill, secondaryFill and tertiaryFill. Don't use fixed grays such as `systemGray3` on materials — [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials)

### Inferences
- A web equivalent of "regular" glass for a floating map toolbar or search pill is roughly: `backdrop-filter: blur(20–30px) saturate(180%)` with a translucent white or black fill, a 1px light inner stroke, and a soft shadow. This is my approximation, not an Apple value. Apple publishes no CSS values.
- Apply glass only to the floating chrome: the search field, map controls, the sheet header, and the legend chip. Keep data panels and cards inside the sheet on solid or standard-material surfaces. Never stack glass on glass.
- Recreate the Apple Maps layout with a **persistent, nonmodal bottom sheet** on mobile, with detents at about 10–15% (peek), about 50% (medium) and about 92% (large), and a grabber. On desktop, use a left-floating inset panel. Inset the sheet from the viewport edges while it is at half height, and make it more opaque at full height, as Liquid Glass does.
- Honor `prefers-reduced-transparency` in CSS (supported in some browsers; unverified) and `prefers-contrast: more` by swapping glass for solid fills.

### Gaps
- Apple publishes no numeric blur radius, tint opacity or corner radius for Liquid Glass or the standard materials, so any CSS values are approximations.
- I did not fetch a primary source describing the Apple Maps app's own sheet (its detent heights and behavior in iOS 26). The sheet description above is inferred.
- I did not verify whether visionOS 26 is officially part of "Liquid Glass". The newsroom summary did not list it.

---

## 3. Motion and springs

### Takeaway
Motion should be purposeful, brief, realistic (following the gesture), **interruptible**, and never the only carrier of information. Avoid motion on frequent interactions. SwiftUI's spring presets all default to a **0.5 s perceptual duration**. They differ in bounce: `smooth` = 0, `snappy` = 0.15, `bouncy` = 0.3.

### Cited Findings
- "Add motion purposefully." Avoid gratuitous animation. Motion should not be the only way to convey important information, so pair it with haptics or audio — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- Make feedback motion realistic: a view that slides down from the top should not be dismissed sideways — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- "Aim for brevity and precision." Generally avoid motion on interactions that happen often — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- "Let people cancel motion." Don't make people wait for an animation to finish — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- For games, target 30–60 fps. On visionOS, avoid sustained oscillation near **0.2 Hz** — [HIG Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- `spring(duration: 0.5, bounce: 0.0, blendDuration: 0)` is the default: 0.5 s, no bounce, critically damped — [SwiftUI spring(duration:bounce:)](https://developer.apple.com/documentation/swiftui/animation/spring(duration:bounce:blendduration:))
- `snappy(duration: 0.5, extraBounce: 0.0)` has a base bounce of **0.15**. Duration is the "perceptual duration", roughly the settling time — [SwiftUI snappy](https://developer.apple.com/documentation/swiftui/animation/snappy(duration:extrabounce:))
- `bouncy(duration: 0.5, extraBounce: 0.0)` has a base bounce of **0.3** — [SwiftUI bouncy](https://developer.apple.com/documentation/swiftui/animation/bouncy(duration:extrabounce:))
- `smooth` is "a smooth spring animation with a predefined duration and no bounce". `interactiveSpring` has a shorter duration and is meant for gesture-driven animation. `interpolatingSpring` preserves velocity across overlapping animations — [SwiftUI Animation](https://developer.apple.com/documentation/swiftui/animation)
- Reduce Motion: "Minimize animations when setting is enabled" — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)

### Inferences
- To convert to web springs (for example Framer Motion `type:"spring"`, `visualDuration: 0.5`, `bounce: 0 | 0.15 | 0.3`): Framer Motion's `bounce` and `visualDuration` model is closely analogous to SwiftUI's duration/bounce model. Using it is my suggestion and was not verified against Apple.
- Use `smooth` (bounce 0) for sheet detent snaps and camera transitions. Use `snappy` (0.15) for button, chip and selection feedback. Avoid `bouncy` in an operations dashboard.
- Map camera `flyTo` animations should be cancellable by any user gesture; MapLibre already does this. Under `prefers-reduced-motion`, replace flights with `jumpTo` or a crossfade.

### Gaps
- Apple docs do not give numeric defaults for `.smooth` duration, or for response and dampingFraction in `spring(response:dampingFraction:)`. Commonly cited values such as response 0.55 and damping 0.825 are **unverified**.

---

## 4. Typography

### Takeaway
iOS text styles at the default Large size range from Large Title 34/41 down to Caption 2 11/13, with Body at 17/22. macOS runs smaller, with Body at 13/16. The minimum sizes are 11 pt on iOS and 10 pt on macOS. **SF fonts may not be embedded or used on non-Apple platforms**, so websites should use the system font stack and let Apple devices render SF natively.

### Cited Findings
- iOS/iPadOS Dynamic Type at the Large (default) size, as weight, size / leading in pt: Large Title Regular 34/41. Title 1 Regular 28/34. Title 2 Regular 22/28. Title 3 Regular 20/25. **Headline Semibold 17/22**. Body Regular 17/22. Callout Regular 16/21. Subhead Regular 15/20. Footnote Regular 13/18. Caption 1 Regular 12/16. Caption 2 Regular 11/13 — [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- macOS text styles, same format: Large Title 26/32. Title 1 22/26. Title 2 17/22. Title 3 15/20. **Headline Bold 13/16**. Body 13/16. Callout 12/15. Subheadline 11/14. Footnote 10/13. Caption 1 10/13. Caption 2 Medium 10/13 — [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- Default and minimum text sizes: iOS 17/11 pt. macOS 13/10. tvOS 29/23. visionOS 17/12. watchOS 16/12 — [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- Prefer Regular, Medium, Semibold or Bold. Avoid Ultralight, Thin and Light. System fonts adjust tracking at every size. Use the built-in text styles and support Dynamic Type — [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- The families are SF (Pro, Compact, Mono, Arabic, Armenian, Georgian, Hebrew, plus Rounded) and New York (serif). They are variable fonts with optical sizing — [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- The font license allows the fonts "solely for creating mock-ups of user interfaces to be used in software products running on Apple's iOS, OS X or tvOS operating systems". It excludes mock-ups for "any non-Apple operating system". "You may not embed the Apple Font in any software programs or other products". It also requires being a registered Apple Developer — [Apple Fonts](https://developer.apple.com/fonts/)
- Accessibility: support text enlargement of at least **200%** (140% on watchOS) — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)

### Inferences
- Web stack: `font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;`. Apple devices render SF Pro from the OS, which is not embedding and so stays compliant. Do **not** self-host SF Pro woff2 files from the developer site.
- Tailwind scale that mirrors iOS: 34/41, 28/34, 22/28, 20/25, 17/22 (semibold for headline), 16/21, 15/20, 13/18, 12/16, 11/13. A desktop dashboard may reasonably use the **macOS** scale (13 px body) for dense panels. Size text in `rem` so browser zoom approximates Dynamic Type.
- Use `font-variant-numeric: tabular-nums` for live counters, since SF has tabular figures. This is a general practice, not an Apple citation.

### Gaps
- I did not open a WebKit or Apple source documenting `-apple-system`, `system-ui`, or the `font: -apple-system-body` Dynamic Type keywords in Safari. These are **unverified** here.

---

## 5. SF Symbols

### Takeaway
SF Symbols has 9 weights, 3 scales and 4 rendering modes, and supports rich animations. Apple lists it as available on its own platforms, and it is covered by Apple's terms. **Do not use SF Symbols on a website.** Use a lookalike open icon set (for example Lucide, Phosphor or Tabler) and match the stroke weight to your text.

### Cited Findings
- **9 weights**, from Ultralight to Black, matched to SF font weights. **3 scales**: small, medium (default) and large, relative to SF cap height — [HIG SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Rendering modes: monochrome, hierarchical (one color with opacity by layer), palette (two or more colors) and multicolor. Variable color shows change over time from 0–100%, not depth. Gradients arrived in SF Symbols 7 — [HIG SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Animations: appear/disappear, bounce, scale, pulse, variable color, replace/magic replace, wiggle, breathe, rotate, and draw on/off (SF Symbols 7+). "Apply judiciously" — [HIG SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Symbols that represent Apple products or features can't be customized. Symbols may not be used in app icons, logos or trademarks. Availability is listed for iOS, iPadOS, macOS, tvOS, visionOS and watchOS — [HIG SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- The current library has more than 7,000 symbols, reported as "SF Symbols 27" (version label as reported by the fetch). The fetch tool rendered the terms as "Apple system-provided images under Xcode license". The app requires macOS Sonoma or later — [SF Symbols](https://developer.apple.com/sf-symbols/)

### Inferences
- Because SF Symbols are licensed as system-provided images for Apple-platform software (Xcode license), exporting SVGs to a public website is very likely outside the license. Treat it as prohibited.
- Mimic the SF look with icons at 1.5–2px stroke, rounded caps, optically sized to the adjacent text, and hierarchical opacity (100% / 60% / 30%) for two-tone icons.

### Gaps
- I did not open the full text of the SF Symbols license or the Xcode license agreement. The explicit "no web use" wording for symbols is **unverified**. The font license's explicit ban (Section 4) is verified.
- The "SF Symbols 27" version label was not cross-checked.

---

## 6. Accessibility

### Takeaway
Hit targets are **44×44 pt by default on iOS (minimum 28×28)** and **28×28 on macOS (minimum 20×20)**. Contrast follows WCAG AA: 4.5:1 for text up to 17 pt, 3:1 for 18 pt+ or bold. Never use color alone to carry meaning. Support Dynamic Type up to 200%, Reduce Motion, Reduce Transparency and Increase Contrast. VoiceOver labels are required, and the grabber must work with VoiceOver.

### Cited Findings
- Control sizes, default / minimum: iOS and iPadOS 44×44 / 28×28 pt. macOS 28×28 / 20×20. tvOS 66×66 / 56×56. visionOS 60×60 / 28×28. watchOS 44×44 / 28×28 — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Spacing: about **12 pt** of padding around controls with a bezel, and about **24 pt** around the visible edges of borderless controls — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Contrast: 4.5:1 for text up to 17 pt, 3:1 for 18 pt+, and 3:1 for bold text of any size — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Never convey information by color alone; use shapes, icons or other indicators. Support Reduce Motion, "Dim Flashing Lights", and no auto-dismiss timers. Provide button alternatives to gestures and full keyboard access — [HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- The sheet grabber supports VoiceOver so people can resize the sheet without seeing it — [HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Liquid Glass adapts to Reduce Transparency, Increase Contrast and Reduce Motion — [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- Combine color with icons to distinguish map feature types — [HIG Maps](https://developer.apple.com/design/human-interface-guidelines/maps)

### Inferences
- Make map buttons at least 44×44 CSS px on touch and at least 28–32 px on desktop pointer layouts.
- Congestion colors (green, amber, red) must have a redundant cue such as line dash, width or icon, and must pass 3:1 against the muted basemap.
- For VoiceOver on a canvas map, MapLibre's WebGL canvas isn't accessible. Provide a parallel list or table of incidents and corridors in the sheet, with `aria-live` for new alerts, and focusable markers or a keyboard-navigable list.

### Gaps
- I found no specific HIG guidance on VoiceOver for map content, such as rotor behavior or annotation ordering, beyond the general labeling rules.

---

## 7. MapKit JS: pricing, tokens, built-in UI, custom rendering

### Takeaway
MapKit JS (currently **v6**) needs an **Apple Developer Program membership** and a **JWT Maps token**. It includes **250,000 map views and 25,000 service calls per day** per membership at no extra cost. It provides built-in controls, annotations with clustering, vector overlays, tile overlays, Look Around and Place Detail. It does **not** document any custom WebGL or GL-context hook, so it is unsuitable if you need MapLibre-style custom WebGL layers such as deck.gl or three.js.

### Cited Findings
- The free daily limit is 250,000 map views and 25,000 service calls per Apple Developer Program membership. Going over the service-call limit returns HTTP 429. The limits are shared with the Apple Maps Server API. Contact Apple for more capacity (search snippet of developer.apple.com/maps/web; the page returned HTTP 500 when fetched directly) — [Apple Maps on the Web (search result)](https://developer.apple.com/maps/web/)
- Apple DTS (January 2020): 250,000 map views and 25,000 service calls per day per membership, requiring a Developer Program membership with no further cost. A developer in November 2024 flagged an inconsistency between "per day" and "per month" on Apple's pages — [Apple Developer Forums #127493](https://developer.apple.com/forums/thread/127493)
- MapKit JS is a JS API for interactive Apple Maps on websites across platforms. It supports annotations, overlays, **Place Detail**, **Look Around**, and search. It requires a **JWT Maps token**. The current version is **6.0** (with a v5→v6 migration guide) and it auto-updates via CDN — [MapKit JS docs](https://developer.apple.com/documentation/mapkitjs)
- Map controls and options: `showsCompass` and `showsScale` (FeatureVisibility), `showsZoomControl`, `showsMapTypeControl`, `showsUserLocationControl`, `isRotationEnabled`, `colorScheme` (light/dark), `mapType` (standard, **mutedStandard**, hybrid, satellite), `showsPointsOfInterest` and `pointOfInterestFilter`, `tintColor`, `padding`, `cameraZoomRange`, `selectableMapFeatures`, `annotationForCluster`, `tileOverlays` — [MapKit JS Map](https://developer.apple.com/documentation/mapkitjs/map)
- Overlays: `CircleOverlay`, `PolylineOverlay`, `PolygonOverlay`, and `TileOverlay` (with imageForTile URL template or callback, opacity, minimumZ/maximumZ, data, reload()). `Style` controls stroke and fill color, opacity and line styles. **No custom WebGL/canvas hook or GL context access is documented** — [MapKit JS TileOverlay](https://developer.apple.com/documentation/mapkitjs/tileoverlay)
- By contrast, Google Maps exposes a `WebGLOverlayView` that shares its GL context for three.js — [Google WebGL Overlay View](https://developers.google.com/maps/documentation/javascript/webgl/webgl-overlay-view)

### Inferences
- Keep MapLibre. Borrow Apple's *design language* rather than MapKit JS. MapKit JS would force DOM or SVG overlays positioned by hand for any custom GPU layer, and would add token infrastructure and quota risk for a live traffic dashboard.
- `mapType: mutedStandard` is MapKit JS's counterpart of the HIG's "muted emphasis". Replicate it in MapLibre with a desaturated style.

### Gaps
- The **$99/yr** Developer Program fee was not verified on a page I opened; the pages I opened state only that membership is required. The per-day vs per-month quota wording is disputed.
- The Map property list came from an automated summary. Exact enum names such as `FeatureVisibility.Adaptive/Visible/Hidden` were not verified.

---

## 8. Apple Maps design evolution and the web version

### Takeaway
Apple Maps on the web launched in **public beta on July 24, 2024** (Safari and Chrome on Mac and iPad, Chrome and Edge on Windows). It **left beta on April 11, 2025**, moved to maps.apple.com, and added mobile browsers including Android and Firefox. Look Around is available through a binoculars button at the top right. Transit, 3D buildings and sign-in were still missing at that time.

### Cited Findings
- Beta launch on July 24, 2024 at beta.maps.apple.com. Supported browsers: Safari and Chrome on Mac and iPad, Chrome and Edge on Windows. English only. Features: driving and walking directions, place cards with photos, hours, ratings and reviews, food ordering, and Guides. Look Around was "coming". MapKit JS developers can link to Maps on the web — [Apple Newsroom](https://www.apple.com/newsroom/2024/07/apple-maps-on-the-web-launches-in-beta/)
- On April 11, 2025 it exited beta and moved to maps.apple.com. It added iPhone and Android mobile browsers, plus Look Around behind the binoculars icon. Transit maps, 3D buildings, account sign-in and saved places were not yet available — [9to5Mac](https://9to5mac.com/2025/04/11/apple-maps-web-mobile/)
- Firefox and Android support, and Look Around at the top right — [Apple Maps web exits beta search results: HowToGeek/Neowin/gHacks](https://www.howtogeek.com/apple-maps-finally-works-in-android-mobile-browsers/) (search snippet only; gHacks returned 403)

### Inferences
- The web UI is a left search/place-card panel over a full-bleed map with floating controls on the right. This is consistent with the HIG's statement that place cards are popovers or callouts on large windows and sheets on phones, but it was **not verified** from a primary description.

### Gaps
- I did not source the 2019 "rebuilt map" (new ground-up map data in iOS 13), so it is unverified here. I also found no primary description of the maps.apple.com layout, such as panel widths or control positions; the 9to5Mac article gives no layout detail. It is unknown whether maps.apple.com adopted Liquid Glass styling after 2025.
