# Accessibility of Interactive Web Maps and UX Patterns for Real-Time Operational Dashboards

Scope: requirements and patterns for a React + MapLibre GL JS traffic-management dashboard (control-room style). Research date: 2026-09-25. Every cited URL was opened during research unless marked **[UNVERIFIED]**. Aggregator / vendor-blog sources are flagged where the primary standard is paywalled.

## WCAG 2.2 success criteria most relevant to interactive maps and live dashboards (exact wording, levels, WCAG 3 status)

### Takeaway
WCAG 2.2 is the current W3C Recommendation (first published 5 Oct 2023; the /TR page now shows a 12 Dec 2024 dated edition). For a live map dashboard, the load-bearing AA criteria are 1.4.3/1.4.11 contrast, 1.4.1 use of colour, 2.1.1 keyboard, 2.2.2 pause/stop/hide (it explicitly covers auto-updating data such as traffic cameras), the three new 2.2 criteria 2.4.11, 2.5.7 and 2.5.8, and 4.1.3 status messages. WCAG 3 is still a Working Draft (latest 10 Sep 2026) and is not expected to become a Recommendation before about 2028.

### Cited Findings
**Status and versions**
- WCAG 2.2 was published as a W3C Recommendation on **5 October 2023**. It adds 9 new SCs, and **4.1.1 Parsing is "obsolete and removed"** — [W3C WAI, What's New in WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)
- The /TR/WCAG22 document now shows status "W3C Recommendation, **12 December 2024**" (an updated edition; the What's New page still says "Updated: 5 October 2023"). I did not confirm what changed in the Dec 2024 edition. It appears editorial, since the SC set is the same — [W3C, WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- New in 2.2, with levels: 2.4.11 Focus Not Obscured (Minimum) **AA**; 2.4.12 Focus Not Obscured (Enhanced) AAA; 2.4.13 Focus Appearance AAA; 2.5.7 Dragging Movements **AA**; 2.5.8 Target Size (Minimum) **AA**; 3.2.6 Consistent Help A; 3.3.7 Redundant Entry A; 3.3.8 Accessible Authentication (Minimum) AA; 3.3.9 Accessible Authentication (Enhanced) AAA — [W3C WAI, What's New in WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)
- **WCAG 3.0**: Working Draft last published **10 September 2026**. W3C says it "still has several years of work" before completion — [W3C WAI news, Sep 2026](https://www.w3.org/WAI/news/2026-09-10/wcag3/); [WCAG 3.0 WD 2026-09-10](https://www.w3.org/TR/2026/WD-wcag-3.0-20260910/). Secondary sources say it moves from A/AA/AAA pass/fail to outcome-based Bronze/Silver/Gold, with a Candidate Recommendation targeted around Q4 2027 and a Recommendation not before 2028. These timeline figures come from search snippets of third-party pages that I did not open in full, so treat them as **[UNVERIFIED — secondary]** (e.g. [AbilityNet](https://abilitynet.org.uk/resources/digital-accessibility/what-expect-wcag-30-web-content-accessibility-guidelines)).

**Normative wording (from [W3C, WCAG 2.2](https://www.w3.org/TR/WCAG22/) unless noted)**
- **1.4.1 Use of Color (A)**: "Color is not used as the only visual means of conveying information, indicating an action, prompting a response, or distinguishing a visual element."
- **1.4.3 Contrast (Minimum) (AA)**: "The visual presentation of text and images of text has a contrast ratio of at least 4.5:1". Exceptions: large text needs only 3:1; incidental text and logotypes are exempt.
- **1.4.11 Non-text Contrast (AA)**: user interface components and graphical objects "required to understand the content" need "a contrast ratio of at least 3:1 against adjacent color(s)". Inactive components and essential presentations are exempt. (Relevance: congestion line colours against the basemap, marker outlines, and map control icons.)
- **2.1.1 Keyboard (A)**: "All functionality of the content is operable through a keyboard interface without requiring specific timings for individual keystrokes, except where the underlying function requires input that depends on the path of the user's movement."
- **2.2.1 Timing Adjustable (A)**: for time limits, the user can turn the limit off, adjust it (at least 10× the default), or extend it (warned, at least 20 s, at least 10 times). (Relevance: auto-dismissing toasts that need action.)
- **2.2.2 Pause, Stop, Hide (A)**, auto-updating clause: "For any auto-updating information that (1) starts automatically and (2) is presented in parallel with other content, there is a mechanism for the user to pause, stop, or hide it or to control the frequency of the update unless the auto-updating is part of an activity where it is essential." — [Understanding 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html). The moving/blinking clause applies to content that starts automatically, lasts more than 5 s, and runs in parallel with other content — [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
  - The Understanding doc names real-time status content directly: "Pausing and jumping to current display (when pause is released) is better for information that is real-time or 'status' in nature. For example, weather radar, a stock ticker, **a traffic camera**…" would be misleading if resumed from old data — [Understanding 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)
  - "Essential" means that removing it "would fundamentally change the information or functionality… **and** information and functionality cannot be achieved in another way that would conform." — [Understanding 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)
- **2.3.1 Three Flashes or Below Threshold (A)**: nothing "flashes more than three times in any one second period" unless it is below the thresholds. (Relevance: flashing emergency markers and alarm blink.)
- **2.4.7 Focus Visible (AA)**: "Any keyboard operable user interface has a mode of operation where the keyboard focus indicator is visible."
- **2.4.11 Focus Not Obscured (Minimum) (AA)**: "When a user interface component receives keyboard focus, the component is not entirely hidden due to author-created content." 2.4.12 (AAA) requires that "no part" be hidden. (Relevance: sticky top bars, floating panels, toasts and legends covering a focused marker or list row.)
- **2.4.13 Focus Appearance (AAA)**: the indicator is at least as large as "a 2 CSS pixel thick perimeter" of the component and has a contrast ratio of at least 3:1.
- **2.5.7 Dragging Movements (AA)**: functionality that uses dragging "can be achieved by a single pointer without dragging, unless dragging is essential" — [Understanding 2.5.7](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html). The full normative text also exempts functionality "determined by the user agent and not modified by the author" **[UNVERIFIED — truncated in fetch]**.
  - The map example appears in the Understanding doc: "A map allows users to drag the view of the map around, and the map has up/down/left/right buttons to move the view as well." — [Understanding 2.5.7](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
  - **Keyboard support alone does not satisfy 2.5.7**: "Achieving keyboard equivalence for a dragging operation does not automatically meet this success criterion, unless that equivalent keyboard operation also provides controls that can be clicked or tapped with a pointer." — [Understanding 2.5.7](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
- **2.5.8 Target Size (Minimum) (AA)**: "The size of the target for pointer inputs is at least 24 by 24 CSS pixels, except when:" Spacing (undersized targets whose 24 px-diameter circles, centred on each target, do not intersect another target or circle); Equivalent (another conforming control on the same page does the same thing); Inline; User agent control; Essential — [Understanding 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
  - Map pins: because pin position is "analogous to the position of places shown on the map", closely spaced pins fall under the **Essential** exception — [Understanding 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- **4.1.3 Status Messages (AA)**: "In content implemented using markup languages, status messages can be programmatically determined through role or properties such that they can be presented to the user by assistive technologies without receiving focus." A status message is a "change in content that is not a change of context" giving results, waiting state, progress, or errors. The sufficient techniques use `role="status"`, `role="alert"`, `role="log"`, and progress bars. The document also warns: "There is a risk of making an application too 'chatty' for a screen reader user" — [Understanding 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

### Inferences
- Live congestion colours, incident counts and vehicle positions are "auto-updating information presented in parallel with other content", so 2.2.2 requires a **Pause live updates / control update frequency** control. On resume, the view should **jump to current** state, not replay from where it paused.
- Map panning must have **on-screen pan buttons** (or click-to-recentre) to meet 2.5.7. MapLibre's arrow-key panning covers 2.1.1 but not 2.5.7.
- Map control buttons (zoom, pan, layer toggles, legend toggles) must be at least 24×24 CSS px. Dense map markers can rely on the Essential exception, but list or table equivalents for them should meet 24×24.
- Floating panels (emergency panel, create-anomaly panel, toasts) must not fully cover the focused element (2.4.11). Test Tab order while panels are open.

### Gaps
- I did not open the exact normative 2.5.7 text, including the user-agent exception, in full.
- I could not confirm what the Dec 2024 WCAG 2.2 edition changed.
- I did not open a primary source for the WCAG 3 Candidate Recommendation and Recommendation timeline.

## Accessible web map techniques (text alternatives, live regions, keyboard, MapLibre/Mapbox/Esri/Google/GOV.UK)

### Takeaway
MapLibre ships keyboard pan, zoom and rotate (enabled by default) and a `reduceMotion` option. It does **not** expose features to screen readers, and the only known plugin, Mapbox's `mapbox-gl-accessibility`, was archived in 2022. So the app must supply its own accessible layer: a labelled map container, a synchronised list or table of incidents, polite live-region summaries, and on-screen pan and zoom buttons. Esri's SDK is the best reference implementation.

### Cited Findings
**MapLibre GL JS**
- The `keyboard` option **defaults to `true`** (keyboard shortcuts on). `dragPan` defaults to true. `cooperativeGestures` defaults to false; when on, it requires Ctrl/Cmd plus scroll to zoom on desktop or two fingers on mobile. `locale` patches UI strings such as control tooltips — [MapLibre MapOptions](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/MapOptions/)
- `reduceMotion`: when `true` it disables gesture inertia. "If unset, defaults to the user's device accessibility preferences." `fadeDuration` defaults to 300 ms (label collision fade) — [MapLibre MapOptions](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/MapOptions/)
- KeyboardHandler shortcuts:
  - `=`/`+` zoom in 1 level; Shift+`=` zoom in 2 levels
  - `-` zoom out 1 level; Shift+`-` zoom out 2 levels
  - Arrow keys pan **100 px** per press
  - Shift+←/→ rotate ±15°; Shift+↑/↓ pitch ±10°
  - Methods: `enable()`, `disable()`, `enableRotation()`, `disableRotation()`
  - Source: [MapLibre KeyboardHandler](https://maplibre.org/maplibre-gl-js/docs/API/classes/KeyboardHandler/)
- MapLibre has examples of "a custom marker element keyboard accessible" and of dragging a marker "with the pointer or keyboard". This comes from a search snippet of the MapLibre examples index; I did not open the example pages — [MapLibre examples](https://maplibre.org/maplibre-gl-js/docs/examples/)
- **mapbox-gl-accessibility** creates `<button>` elements over features in chosen `layers`, using `accessibleLabelProperty` as the spoken text, so screen-reader users can Tab through map features. It was **archived and read-only as of 21 Sep 2022** — [GitHub mapbox/mapbox-gl-accessibility](https://github.com/mapbox/mapbox-gl-accessibility)

**Esri ArcGIS Maps SDK for JavaScript (reference implementation)**
- The map/scene view container has **ARIA `role="application"`** and needs an accessible name. The `aria` property supports `label`, `description`, `labelledByElements` and `describedByElements` — [ArcGIS JS SDK Accessibility](https://developers.arcgis.com/javascript/latest/accessibility/)
- ARIA live regions announce bookmark selections and search results automatically — [ArcGIS JS SDK Accessibility](https://developers.arcgis.com/javascript/latest/accessibility/)
- The Popup traps focus while open and returns focus to the triggering element when it closes (`focusTrapDisabled` opts out) — [ArcGIS JS SDK Accessibility](https://developers.arcgis.com/javascript/latest/accessibility/)
- The SDK respects `prefers-reduced-motion` by disabling navigation animations and momentum panning — [ArcGIS JS SDK Accessibility](https://developers.arcgis.com/javascript/latest/accessibility/)
- Search snippets add that some interactions, such as drawing with the Draw widget, "do not yet support keyboard navigation or screen readers". There is also an open Esri community idea asking for keyboard navigation *between map features*, which suggests feature-level keyboard access is an unsolved gap even in Esri — [Esri Community idea](https://community.esri.com/t5/arcgis-javascript-maps-sdk-ideas/accessibility-keyboard-navigation-to-navigate/idi-p/1670218) **[snippet only, not opened]**
- Minnesota IT Services publishes an "Accessibility Guide for Interactive Web Maps" (PDF) — [MN.gov](https://mn.gov/mnit/assets/Accessibility%20Guide%20for%20Interactive%20Web%20Maps_tcm38-403564.pdf) **[not opened]**

**ARIA live regions (MDN)**
- `aria-live="polite"` announces when the user is idle and is recommended for most updates. `assertive` interrupts, "can be extremely disruptive", and should be used only for critical, time-sensitive alerts — [MDN, ARIA live regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- Implicit live roles:
  - `status` and `log`: polite; add a redundant `aria-live="polite"` for compatibility
  - `alert`: assertive; MDN says not to combine it with `aria-live` for iOS VoiceOver
  - `timer` and `marquee`: implicitly `aria-live="off"`
  - Source: [MDN](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- `aria-atomic="true"` announces the whole region (the clock example). `aria-relevant` defaults to `"additions text"` — [MDN](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- **The live region must already exist in the DOM before its content changes.** If you add one dynamically, defer the content update (e.g. with `setTimeout`) — [MDN](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)

**WAI-ARIA APG feed pattern (for live incident lists)**
- A feed loads content dynamically. While articles are being added or removed, the `feed` element has `aria-busy="true"`, and setting it back to `false` is "extremely important". Keyboard: Page Down/Up move between articles; Ctrl+End/Ctrl+Home leave the feed. Articles carry `aria-posinset` and `aria-setsize` (use `-1` if the total is unknown) — [WAI-ARIA APG Feed](https://www.w3.org/WAI/ARIA/apg/patterns/feed/)

### Inferences
- **Map container**: give it `role="application"` (following Esri) or `role="region"`, with `aria-label` like "Traffic map" and `aria-describedby` pointing at a text summary such as "12 corridors, 3 congested, 1 active emergency route". Note that `role="application"` stops screen-reader browse keys inside the map, so every function must be keyboard-reachable.
- **Text alternative**: a synchronised, sortable HTML table or list of incidents, signals and corridors (name, status in words, time) is the practical screen-reader equivalent. Selecting a row should fly the map to that item, and the reverse. This also gives an Equivalent path for 2.5.8.
- **One polite live region** for map state summaries, debounced and coalesced (e.g. at most one announcement every few seconds, summarising "3 new incidents"). Use a separate `role="alert"` only for the highest-priority events, such as a new emergency vehicle corridor. MDN and W3C both warn against chattiness, but neither gives a numeric rate. The debounce interval is a design choice, not a standard.
- Honour `prefers-reduced-motion` for `flyTo`/`easeTo` (use `jumpTo`) and for pulsing markers, and leave MapLibre's `reduceMotion` unset so it follows the OS setting.
- Put a **visible keyboard-shortcut hint** near the map (arrow = pan 100 px, +/- = zoom), since MapLibre shortcuts are not discoverable.

### Gaps
- I found no maintained MapLibre-specific screen-reader plugin; this is a real ecosystem gap, not just a search miss.
- I did not research Google Maps' own accessibility features or GOV.UK's map-specific guidance; GOV.UK has no map component that I found.
- I did not locate academic research on screen-reader map summaries (e.g. auto-generated spatial descriptions) within the tool budget.

## Colour: colour-blind-safe congestion palettes and redundant encoding

### Takeaway
A green, amber, red congestion ramp breaks for deuteranopia and protanopia and also violates 1.4.1 if colour is the only cue. Use an ordered ramp that varies in **lightness** (plus hue), redundant encoding (line width, dash pattern, labels or icons), and 3:1 contrast against the basemap for 1.4.11.

### Cited Findings
- About **300 million people** have colour vision deficiency, roughly **1 in 12 men**. TomTom added "high-contrast dedicated color schemes" in Map Styler for deuteranopia, protanopia and tritanopia, avoids pairs like red and green, and recommends "line widths, patterns and other visual textures and cues" as complements (article dated 19 May 2022) — [TomTom Newsroom](https://www.tomtom.com/newsroom/behind-the-map/mapping-for-color-blindness/)
- WCAG 1.4.1 forbids colour as the only visual means of conveying information — [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- WCAG 1.4.11 requires graphical objects needed for understanding (e.g. congestion lines) to have 3:1 contrast against adjacent colours — [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- GOV.UK: success banners must use a non-colour-dependent heading such as "Success" — [GOV.UK Design System, Notification banner](https://design-system.service.gov.uk/components/notification-banner/)
- Search-snippet-level guidance (not opened): viridis/cividis-style ordered ramps, blue/orange pairs and the Okabe-Ito palette are commonly cited as CVD-safe — [Visualising Data](https://visualisingdata.com/2019/08/five-ways-to-design-for-red-green-colour-blindness/); [UX Collective, accessible traffic light colors](https://uxdesign.cc/beautiful-accessible-traffic-light-colors-b2b14a102a38) **[UNVERIFIED]**

### Inferences
- For congestion, encode **severity with lightness plus width**: free flow thin and light, heavy congestion thick and dark. Optionally add dashes for "closed/blocked" and an icon for incidents. Keep the conventional green/amber/red hues if operators expect them, but shift them so they separate by lightness (e.g. a yellowish green, orange, deep magenta-red). Check with a CVD simulator.
- The legend must use words ("Free flow / Slow / Stopped / Closed"), not just swatches. Tooltips and list rows should state the status in text.

### Gaps
- I found no published, validated CVD-safe palette specifically for traffic congestion from a mapping vendor (Google, Apple, TomTom, HERE) with exact hex values.

## Real-time dashboard UX: stable lists, freshness and stale states, alert fatigue, notifications, update rates, control-room human factors

### Takeaway
Control-room practice (ISA-101, ISA-18.2, EEMUA 191) says:
- Keep the normal screen visually quiet so abnormal states stand out.
- Hold alarm rates near 1 per 10 minutes per operator in steady state; above 10 per 10 minutes is a flood.
- Give every live widget a visible last-updated time, a pause control, and a rate limit.
- Use notifications sparingly, and never auto-dismiss anything that needs action.

### Cited Findings
**Alarm management (ISA-18.2 / EEMUA 191 / IEC 62682)**
- EEMUA 191 (**4th edition, November 2024**): "no more than one alarm per operator per ten minutes during normal operations; roughly 150 alarms per operator per day". During a major upset, "no more than ten alarms should present in the first ten minutes". ANSI/ISA-18.2-2016, EEMUA 191 and IEC 62682 are described as aligned. The top ten "bad actor" alarms typically cause 60–80% of occurrences — [Seqent, Alarm Rationalization Explained](https://seqent.com/blog/alarm-rationalization-explained/) (vendor blog; primary standards are paywalled)
- The ISA-18.2 alarm-flood definition (≥10 alarms in 10 minutes), standing alarms below 10 per operator, and a priority split of about 5% high, 15% medium, 80% low come from search snippets of vendor and aggregator pages — [Industry Digits](https://industrydigits.com/resources/alarm-load-scorer/); [RailNetOps](https://railnetops.com/guides/alarm-flood-reduction-rail-control-rooms/) **[UNVERIFIED — secondary, not opened]**

**HMI design (ISA-101)**
- ISA-101 "high-performance HMI": the normal state is low-contrast greyscale and saturated colour is reserved for abnormal conditions, so that "anything coloured on the screen is by definition something wrong". One source claims a 48% improvement in detecting abnormal situations before alarms occur — [LADX, ISA-101](https://ladx.ai/resources/isa-101-hmi-design); [Industrial Monitor Direct](https://industrialmonitordirect.com/blogs/knowledgebase/isa-101-high-performance-hmi-design-principles-color-strategy) **[search snippets only; the 48% figure is UNVERIFIED and its original study was not identified]**

**Freshness, pause and rate limiting (Microsoft Fabric Real-Time Dashboards, doc dated 2026-05-27)**
- Live refresh updates visuals only when new data is ingested. A **"Refresh rate limit"** sets "a minimum time interval between refreshes to prevent excessive updates during high-frequency data ingestion", and a fallback interval covers unsupported visuals — [Microsoft Learn](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh)
- "Each visual displays its **last refresh timestamp**". Hovering shows when data was last refreshed and **when the source was last checked**. There is a manual Update button per visual — [Microsoft Learn](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh)
- Viewers can **pause** live refresh "if you're investigating a specific data point". The paused state is shown by a strike-through button and a tooltip saying "Visuals don't refresh automatically." — [Microsoft Learn](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/dashboard-live-refresh)
- Grafana alerting has explicit **No Data** and **Error** states for rule evaluation, separate from Normal/Alerting — [Grafana docs, No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/) **[title and snippet only; not opened]**

**Perception and response limits**
- Nielsen (1993):
  - **0.1 s**: feels instantaneous
  - **1.0 s**: the delay is noticed but the "flow of thought" stays intact
  - **10 s**: the limit of attention; progress feedback is needed
  - Source: [NN/g, Response Times: The 3 Important Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)
- WCAG 2.3.1 caps flashing at 3 per second, which is a hard ceiling for any blinking alarm marker — [WCAG 2.2](https://www.w3.org/TR/WCAG22/)

**Notifications**
- GOV.UK: "Use notification banners sparingly. There's evidence that people often miss them, and using them too often is likely to make this problem worse." Show at most one banner per page and combine messages. Standard banners use `role="region"` + `aria-labelledby`; success banners use `role="alert"` — [GOV.UK Design System, Notification banner](https://design-system.service.gov.uk/components/notification-banner/)
- Auto-dismissing a toast that needs action is a time limit under WCAG 2.2.1, so the user must be able to turn it off, extend it, or adjust it — [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- Live lists: the APG feed pattern gives `aria-busy` batching and article-level keyboard navigation for dynamically inserted items — [WAI-ARIA APG Feed](https://www.w3.org/WAI/ARIA/apg/patterns/feed/)

### Inferences
Concrete requirements for the traffic dashboard:
- **Quiet baseline**: keep the basemap and normal-flow roads desaturated or grey, and reserve saturated red and magenta for incidents and emergencies (ISA-101 principle).
- **Alarm budget**: treat about 1 operator-actionable alert per 10 minutes as the steady-state target. If more than 10 arrive in 10 minutes, switch to flood mode: group related events into a single incident, suppress downstream "consequence" alerts (e.g. congestion caused by a known incident), and show a count instead of individual toasts.
- **Stable live lists**: don't re-sort rows while the pointer or focus is inside the list. Buffer new items behind an "N new incidents — show" button (a polite live region announces the count), and apply the batch with `aria-busy`. Reserve fixed row heights to avoid layout shift. This "N new updates" pattern follows from 2.2.2 (control over update frequency) and 2.4.11. I found **no NN/g article specifically codifying it** in this pass.
- **Freshness**: a global "Live · updated 3 s ago" indicator plus per-panel timestamps. After a threshold (e.g. several missed update intervals), switch to an explicit **Stale / Degraded** state: greyed or hatched data, amber banner "Live feed lost — showing data from 14:02:10", distinct from "No data". Resuming from pause jumps to current state (Understanding 2.2.2).
- **Update cadence**: throttle visual updates to about 1 Hz for numbers and positions. Animate vehicle positions smoothly between updates only when reduced motion is off. Throttle screen-reader announcements much more slowly (coalesced summaries). The 1 Hz figure is a design inference from the NN/g 0.1 s / 1 s limits, not a cited standard.
- **Notification tiers**:
  - Critical (new emergency corridor): persistent, `role="alert"`, needs acknowledgement, never auto-dismisses.
  - Warning: toast plus inbox entry, `role="status"`.
  - Info: inbox or log only (`role="log"`).
  - Keep an alarm/event history panel ("inbox") so dismissed toasts are recoverable.

### Gaps
- **Carbon Design System** notification and accessibility pages could not be fetched (content truncated), so I have no Carbon toast timing or role details.
- I did not fetch Atlassian or Grafana design guidance directly.
- I did not open the ISA-101, ISA-18.2 or EEMUA 191 primary texts (paywalled); the figures come from vendor summaries. The 4th-edition November 2024 date for EEMUA 191 comes from one vendor blog and should be double-checked.
- I found no peer-reviewed human-factors source giving a specific maximum perceivable update rate for dashboards; "1 Hz" is inferred.
- I found no authoritative NN/g source for the "N new items" pattern in this pass.
