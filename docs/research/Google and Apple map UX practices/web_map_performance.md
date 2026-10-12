# Web map performance engineering (Google Maps web + React 18 / Vite / MapLibre GL JS 4)

Research date: 2026-09-25. Each source was opened (WebFetch) unless it is marked **[search snippet only]** or **[unverified]**.

## Core Web Vitals thresholds, percentile, INP replacing FID, and mobile JS budgets

### Takeaway
The "good" targets are LCP ≤2.5 s, INP ≤200 ms and CLS ≤0.1, measured at the 75th percentile and split by mobile and desktop. INP replaced FID on 12 March 2024. Alex Russell's 2024 budget for a JS-heavy SPA that must become interactive in 3 s on a mid-range Android phone is about 365 KiB of compressed JS (650 KiB for a 5 s target).

### Cited Findings
- LCP: good ≤2.5 s, needs improvement 2.5–4.0 s, poor >4.0 s. INP: good ≤200 ms, needs improvement 200–500 ms, poor >500 ms. CLS: good ≤0.1, needs improvement 0.1–0.25, poor >0.25. The page was last updated 31 Oct 2024. — [web.dev Web Vitals](https://web.dev/articles/vitals)
- Scores are assessed at the **75th percentile** of page loads, split by mobile and desktop. — [web.dev Web Vitals](https://web.dev/articles/vitals)
- INP became a Core Web Vital and replaced FID on **12 March 2024**. Search Console dropped FID the same day. PageSpeed Insights and CrUX had a 6-month deprecation window. — [web.dev blog: INP CWV March 12](https://web.dev/blog/inp-cwv-march-12)
- An INP interaction has three phases: input delay, processing duration and presentation delay. The guidance is to yield with `setTimeout`, or with `requestAnimationFrame` followed by `setTimeout` so non-critical work runs after paint. It also says to avoid reading layout right after writing styles (layout thrashing), keep the DOM small, and use `content-visibility`. The page was last updated 2 Sep 2025. — [web.dev Optimize INP](https://web.dev/articles/optimize-inp)
- Alex Russell's 2024 budgets (P75 users, compressed transfer):
  - JS-heavy sites, 3 s target: 730 KiB total, of which **365 KiB JS**.
  - JS-heavy sites, 5 s target: 1.3 MiB total, of which **650 KiB JS**.
  - Markup-centric sites, 3 s target: 75 KiB JS, 1.4 MiB total.
  - Markup-centric sites, 5 s target: 100 KiB JS, 2.5 MiB total.
  - Reference device: Samsung Galaxy A51. Network: 7.2 Mbps down, 1.4 Mbps up, 94 ms RTT.
  - Source: [infrequently.org, Performance Inequality Gap 2024](https://infrequently.org/2024/01/performance-inequality-gap-2024/)

### Inferences
- maplibre-gl alone is several hundred KB minified. A map dashboard therefore needs most of the 365 KiB (3 s) JS budget for the map. The landing and marketing routes should stay near the "markup-centric" budget, and maplibre and three.js should be split into route-level chunks.
- The dashboard will be judged mostly on INP (map interactions, list filtering) and CLS (live lists). LCP matters most on the landing route.

### Gaps
- I did not find or open a 2025 or 2026 edition of Russell's budget post. The 2024 numbers are the latest I verified.
- I did not open the exact date FID was fully removed from PSI and CrUX. The only verified fact is "6 months" after 12 March 2024.

## Code splitting in React and Vite, and lazy-loading heavy libraries

### Takeaway
Declare `React.lazy` at module scope and wrap it in `<Suspense>`, or use react-router's route `lazy` with `Promise.all` to split per route. Vite then emits separate chunks and preloads their shared dependencies in parallel. Heavy libraries (three.js on the landing page, maplibre-gl on the console) should be reachable only through dynamic `import()`.

### Cited Findings
- `React.lazy(() => import('./X'))`:
  - The module must default-export the component.
  - The component must be declared at module top level. Declaring it inside another component resets all state on re-render.
  - It suspends until loaded, rejections go to the nearest Error Boundary, and the load result is cached.
  - Source: [react.dev lazy](https://react.dev/reference/react/lazy)
- A react-router route `lazy` function can return `Component`, `loader` and other route properties. Loading them in parallel with `Promise.all` avoids a waterfall. — [React Router route object](https://reactrouter.com/start/data/route-object)
- Vite rewrites code-split dynamic imports with a preload step, so shared chunk C is fetched in parallel when async chunk A is requested. — [vite.dev Features](https://vite.dev/guide/features)
- Vite adds `<link rel="modulepreload">` for entry chunks and their direct imports. — [vite.dev Features](https://vite.dev/guide/features)
- Vite extracts CSS from async chunks into separate files and loads them with the chunk. — [vite.dev Features](https://vite.dev/guide/features)
- Google Maps JS API does the same thing at the library level. A small inline bootstrap loader defines `google.maps.importLibrary()`, and each library is fetched on demand (`const { Map } = await google.maps.importLibrary("maps")`). Google recommends this "dynamic import" for performance. The direct script tag loads all libraries up front. — [Google Maps: Load the Maps JS API](https://developers.google.com/maps/documentation/javascript/load-maps-js-api)

### Inferences
- One way to preload is to call the route's `import()` on hover or focus of the nav link, or during idle time after first paint. Chunk caching makes the later real import instant. This is an inferred pattern and not quoted from the sources above.
- `manualChunks` can give maplibre-gl and three its own stable-hash vendor chunk so app deploys do not bust their cache.

### Gaps
- I did not open Vite's `build.rollupOptions.output.manualChunks` doc page. Its syntax and behaviour under Vite 6/7 (Rolldown) are unverified.
- I did not verify which React Router version added the object form of "granular lazy".

## Google Maps web engineering (vector maps, WebGL, loading)

### Takeaway
Google's web vector map draws vector tiles on the client with WebGL; Tilt/Rotation and WebGL Overlay View went GA in June 2022 on a WebGL 2 context. Loading is modular through `importLibrary`. I found no public numbers on Google Maps web performance.

### Cited Findings
- The vector map was announced at Google I/O 2021 as "the first WebGL-accelerated map" for web apps. Vector tiles are drawn at load time on the client with WebGL. It allows up to 67.5° tilt and 360° rotation. — [Google Maps Platform blog, Using new WebGL-powered maps features](https://mapsplatform.google.com/resources/blog/using-new-webgl-powered-maps-features/) **[search snippet only]**
- WebGL Overlay View hooks into the same WebGL rendering context as the basemap. This gives depth occlusion with 3D buildings and keeps 2D/3D overlays in sync with basemap rendering. — [Google WebGL Overlay View docs](https://developers.google.com/maps/documentation/javascript/webgl/webgl-overlay-view) **[search snippet only]**
- On **9 June 2022**, Tilt/Rotation, Move Camera and WebGL Overlay View went GA. The release upgraded to a WebGL 2.0 context and claimed "faster real-time rendering" and "reduced video memory consumption", with no numbers. — [GMP blog, WebGL-powered maps features now GA](https://mapsplatform.google.com/resources/blog/webgl-powered-maps-features-now-generally-available/)
- `importLibrary` avoids loading the API twice and defers downloading features until they are needed. — [Google Maps: Load the Maps JS API](https://developers.google.com/maps/documentation/javascript/load-maps-js-api)

### Inferences
- Google has two main patterns: one GL context shared by the basemap and overlays, and modular lazy loading of libraries. Both carry over to MapLibre: add custom layers to the same map instead of a second canvas, and dynamic-import the map chunk.

### Gaps
- I found no Google I/O, Chrome Dev Summit or web.dev case study with metrics for maps.google.com itself (bundle size, LCP or INP). No numbers can be cited.
- I found no Uber, Airbnb or Figma engineering blog on persistent WebGL maps within the call budget. That is unresearched, not evidence that no such posts exist.

## MapLibre GL JS runtime guidance (one persistent map, data updates, workers, symbols)

### Takeaway
Create the map once and keep it across views. If you must remount, call `prewarm()` and/or reuse the instance, as react-map-gl's `reuseMaps` does. Update data with `updateData` diffs or `feature-state`, not full `setData` calls. Use fewer layers and sources. Put fast-changing features in a small separate source.

### Cited Findings
- `prewarm()` creates the WebWorkers that all maps share, ahead of time. Without it they are created lazily when the first Map appears. It is meant for SPAs "where users navigate between different views" and maps are "constantly instantiated and removed". Call `setWorkerCount()` and `setWorkerUrl()` before `prewarm()`. `clearPrewarmedResources()` frees the workers. — [MapLibre prewarm()](https://maplibre.org/maplibre-gl-js/docs/API/functions/prewarm/)
- The default worker count is 1, except on Safari, where it is half the CPU cores capped at 3. `setWorkerCount()` must run before any map is created. In v4.0.0 the global `workerCount` getter/setter became `getWorkerCount()`/`setWorkerCount()`. — [MapLibre setWorkerCount](https://maplibre.org/maplibre-gl-js/docs/API/functions/setWorkerCount/), [v4.0.0 release](https://github.com/maplibre/maplibre-gl-js/releases/tag/v4.0.0) **[search snippet only]**
- `GeoJSONSource.setData(data)` replaces the whole dataset. Passing a URL is "preferable in the case of large GeoJSON files". `updateData(diff: GeoJSONSourceDiff)` applies an incremental diff and "can be used to make updates more quickly". It needs a unique ID on every feature, either `feature.id` or `promoteId`, and is an error on a source without unique IDs. Updates to missing IDs are best-effort. — [MapLibre GeoJSONSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/)
- MapOptions defaults relevant to performance:
  - `fadeDuration` 300 ms (label-collision fade)
  - `maxTileCacheZoomLevels` 5
  - `maxTileCacheSize` null (sized to the viewport)
  - `validateStyle` true ("If false … tree-shaking and minor performance improvements" in production)
  - `crossSourceCollisions` true
  - `cancelPendingTileRequestsWhileZooming` true
  - `pixelRatio` = devicePixelRatio
  - `trackResize` true
  - `canvasContextAttributes` defaults: `antialias:false`, `powerPreference:'high-performance'`, `preserveDrawingBuffer:false`, `contextType:'webgl2'`
  - Source: [MapLibre MapOptions](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/MapOptions/)
- Mapbox guidance, which applies to MapLibre because the render path is shared:
  - Render cost ≈ number of sources + number of layers + number of vertices.
  - Merge layers with data-driven styling. Layers with the same type, source, source-layer, zoom, filter and layout render faster together.
  - Prefer vector tiles over GeoJSON for large, rarely changing data.
  - Use `setFeatureState` for hover and selection. It "reduces layer update time by inserting runtime data without reprocessing geometries".
  - Keep "one large static dataset + one small dynamic source". Avoid frequent `setData` on large GeoJSON.
  - Set `minzoom`/`maxzoom` on layers. Prefer `==` over `match`.
  - Source: [Mapbox GL JS performance](https://docs.mapbox.com/help/troubleshooting/mapbox-gl-js-performance/)
- react-map-gl `reuseMaps` keeps the underlying Map instance when the component unmounts and reuses it on remount. It is for UIs that "frequently mount/unmount map(s) … tabbed or collapsable UI" and avoids recreating "the Map and its data cache". Caveat: only reactive props and `initialViewState` apply on reuse. — [react-map-gl Map (maplibre)](https://visgl.github.io/react-map-gl/docs/api-reference/maplibre/map)
- WebGL context limits:
  - The warning is "Too many active WebGL contexts. Oldest context will be lost." Chromium is reported to default to **16** contexts per tab, and some reports cite 8 on Android. — [Chromium issue 40939743](https://issues.chromium.org/issues/40939743) (page needed sign-in; **[search snippet only / unverified]**), [Masque.jl #125](https://github.com/jowch/Masque.jl/issues/125) **[search snippet only]**
  - Conflicting report: an OpenLayers user hit the limit at **30** contexts on Chromium 127 (Aug 2024). Firefox did not show the limit. — [OpenLayers #16118](https://github.com/openlayers/openlayers/issues/16118)

### Inferences
- For a React 18 SPA:
  - Keep the MapLibre instance in a layout route above the console routes, or hold it in a module-level singleton and re-parent its container. Routes then change sources and layers instead of remounting the map.
  - This avoids repeated context creation, re-downloading the style and glyphs, and losing the tile cache. It also removes the risk of leaking contexts under React StrictMode double-mount in development.
- Lowering `fadeDuration` (for example to 0) makes live-updating labels pop in without a 300 ms fade. This trades polish for immediacy.
- Set `validateStyle:false` in production builds.
- Moving vehicles and signals belong in a small dynamic GeoJSON source updated with `updateData` or `feature-state` and batched to one update per animation frame. Road geometry belongs in a static source.
- The three.js landing globe and the MapLibre map are two WebGL contexts. The globe's renderer should be released (`renderer.dispose()`, `forceContextLoss()`) when leaving the landing page.

### Gaps
- I did not open MapLibre docs for symbol and icon performance (sprite vs `addImage`, `icon-allow-overlap`, `symbol-sort-key` cost). They are unverified.
- The exact current Chromium context limit is unverified: 16 comes from snippets, 30 comes from one report. It varies by platform and version.
- I did not research how Uber, kepler.gl or Mapbox Studio keep a persistent map. kepler.gl is built on deck.gl, and the details are unverified.

## Image formats for large textures (AVIF/WebP vs JPEG, KTX2/Basis)

### Takeaway
AVIF can save more than 50% over JPEG for some content, but web.dev's own example saved only about 6%. For WebGL globe textures, KTX2 with Basis Universal keeps textures compressed in GPU memory, which JPEG, WebP and AVIF cannot do because they decode to raw RGBA.

### Cited Findings
- web.dev (last updated 7 Jun 2021): AVIF offers "significant compression gains" over JPEG and WebP, with research suggesting ">50% savings vs. JPEG". In the article's own 1120×840 example, AVIF was 18,769 B vs JPEG 20,036 B, about 6%. It cites AVIF support from Chrome 85. — [web.dev AVIF](https://web.dev/articles/compress-images-avif)
- three.js `KTX2Loader`:
  - It loads KTX2 containers and transcodes Basis Universal at runtime to whichever GPU-native compressed format the device supports.
  - The fetched summary claimed smaller downloads and a lower VRAM footprint. **[unverified]**: those claims came from the tool's paraphrase, not quoted text.
  - It needs `setTranscoderPath()` (Basis WASM) and `detectSupport(renderer)`.
  - Source: [three.js KTX2Loader docs](https://threejs.org/docs/#examples/en/loaders/KTX2Loader)

### Inferences
- An 8K equirectangular Earth texture decodes to 8192×4096×4 B ≈ 128 MiB of RGBA before mipmaps, whatever the transfer format. That is arithmetic, not a cited figure. KTX2 (UASTC or ETC1S) cuts GPU memory by several times, which matters on mobile.
- For photographic hero or landing images that are not WebGL textures, serve AVIF with a WebP or JPEG fallback through `<picture>`.

### Gaps
- I found no systematic, current (2024–2026) AVIF vs WebP vs JPEG benchmark in the opened sources.
- I did not verify exact KTX2 GPU memory ratios (for example ETC1S ≈ 4 bpp vs RGBA8 32 bpp).

## Layout shift in live-updating lists

### Takeaway
CLS takes the worst "session window": shifts less than 1 s apart, capped at 5 s total. Only shifts within 500 ms of a discrete input (tap, click, key) are excluded. Live updates with no user input always count. Animate with `transform`, reserve space, and use `content-visibility` with `contain-intrinsic-size` for long lists.

### Cited Findings
- A session window groups layout shifts that are less than 1 s apart, with a 5 s maximum. CLS is the window with the largest total. — [web.dev CLS](https://web.dev/articles/cls)
- Shifts within 500 ms of user input get `hadRecentInput` and are excluded. Only discrete inputs count; scrolls, drags and pinch-zoom are "not considered recent input". — [web.dev CLS](https://web.dev/articles/cls)
- Use `transform: scale()` and `transform: translate()` instead of changing size or position properties, so movement does not create layout shifts. — [web.dev CLS](https://web.dev/articles/cls)
- `content-visibility: auto` skips rendering for off-screen elements. The example showed 232 ms → 30 ms (about 7×). Pair it with `contain-intrinsic-size` (the `auto` keyword remembers the last rendered size) so elements do not collapse to 0 height. Support: Chrome/Edge 85, Firefox 125, Safari 18. It became Baseline Newly available on 15 Sep 2025. — [web.dev content-visibility](https://web.dev/articles/content-visibility)

### Inferences
- A live incident or anomaly list that reorders on WebSocket pushes, with no user input, adds to CLS on every reorder. Mitigations:
  - Give rows a fixed height.
  - Sort stably, for example by creation time within a severity bucket.
  - Insert new items at a position the user is not looking at, or behind a "N new" pill.
  - Animate reorders with FLIP (transform only), for example framer-motion `layout`.
- Because pinch and drag on the map are not "recent input", panel changes triggered by map movement also count toward CLS.

### Gaps
- I did not verify whether a transform-based FLIP reorder produces zero layout-shift entries. By spec, transforms do not create layout shifts, but that was not tested here.

## Real-user monitoring with `web-vitals`

### Takeaway
Import from `web-vitals/attribution`, which is about 1.5 K larger than the standard build's ~3 K brotli. You get INP phase breakdowns, the LCP subparts and the element that caused the largest CLS shift. Send them with `navigator.sendBeacon`.

### Cited Findings
- The attribution build is imported from `'web-vitals/attribution'`. It is "slightly larger than the standard build (by about 1.5K, brotli'd)". — [GoogleChrome/web-vitals](https://github.com/GoogleChrome/web-vitals)
- Attribution fields:
  - INP: `interactionTarget`, `interactionType`, `inputDelay`, `processingDuration`, `presentationDelay`, `loadState`.
  - LCP: `target`, `url`, `timeToFirstByte`, `resourceLoadDelay`, `resourceLoadDuration`, `elementRenderDelay`.
  - CLS: `largestShiftTarget`, `largestShiftTime`, `largestShiftValue`, `loadState`.
  - Source: [GoogleChrome/web-vitals](https://github.com/GoogleChrome/web-vitals)
- `reportAllChanges: true` reports every change in a metric's value. The recommended transport is `navigator.sendBeacon('/analytics', body)` because it works during unload. Current metrics are CLS, FCP, INP, LCP and TTFB, and FID is gone. — [GoogleChrome/web-vitals](https://github.com/GoogleChrome/web-vitals)

### Inferences
- For this app, send `{name, value, rating, id, navigationType, attribution}` to an api-service endpoint and tag each record with the SPA route. Soft navigations inside the console are not separate page loads for CWV, so INP and CLS build up over the whole session.

### Gaps
- I did not verify which web-vitals major version removed `onFID` (believed to be v4, **[unverified]**).
- I did not check the status of the soft-navigations API or its support in web-vitals as of Sept 2026.
