# How Google and Apple Engineer and Ship Software, and What a 1–3 Person Capstone Team Can Adopt

Research date: 2026-09-25. Source dates: Malte Ubl post (Jul 2020); *Software Engineering at Google* (SWE book, O'Reilly; publication year about 2020, not checked against the book's own page); SRE book (about 2016) and SRE Workbook (about 2018), years not checked against the pages; Google Testing Blog posts 2015/2016/2024; Apple pages were current as of Sept 2026 (the beta site lists the "27" OS versions). The Google eng-practices pages are living docs with no date on the page.

## 1. Design docs at Google

### Takeaway
Google design docs are informal and written in Google Docs. They follow a common skeleton: context and scope, goals and non-goals, the design with its trade-offs, alternatives considered, and cross-cutting concerns such as security, privacy and observability. A full doc runs 10–20 pages and a "mini design doc" runs 1–3 pages. Skip the doc when the solution is obvious.

### Cited Findings
- The post is "Design Docs at Google" by Malte Ubl, published July 6, 2020 — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- The sections are: **Context and scope** (objective background, kept short); **Goals and non-goals** (the non-goals are things that could reasonably be goals but are deliberately excluded, e.g. "ACID compliance"); **The actual design** (an overview, then details, with the emphasis on trade-offs); **Alternatives considered** (other viable designs and why they were rejected); **Cross-cutting concerns** (security, privacy, observability) — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- Length: 10–20 pages for larger projects; "mini design docs" of 1–3 pages for incremental improvements or sub-tasks — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- Lifecycle: (1) creation and rapid iteration, often in Google Docs; (2) review, which can be lightweight or formal; (3) implementation and iteration, updating the doc as reality diverges; (4) maintenance and learning — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- When not to write one: when the solution is obvious and there is no ambiguity to resolve, the doc is pure overhead — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- Key principle, quoted: "our job is not to produce code per se, but rather to solve problems" — [industrialempathy.com](https://www.industrialempathy.com/posts/design-docs-at-google/)
- Google's privacy team "participates in Google product launches by reviewing design documentation and performing code reviews to ensure that privacy requirements are followed." Cryptography specialists review launches that include crypto implementations. This means the design doc is also an input to privacy and security review — [Google Cloud security overview whitepaper](https://docs.cloud.google.com/docs/security/overview/whitepaper)

### Inferences
- For a capstone team, a 1–3 page "mini design doc" per major feature is the right size. Good candidates in this project: the anomaly-response workflow, the green-corridor routing, and the basemap choice. Use the five headings, and make the cross-cutting section cover privacy (camera/vision data), security, observability and accessibility.
- The non-goals section helps scope control the most in a time-boxed capstone, because it lists what the team will not build.

### Gaps
- I did not open the SWE book's documentation chapter, so it is not cited on design-doc review mechanics. The Ubl post is the primary source here.

## 2. Code review (Google eng-practices, SWE book; Apple)

### Takeaway
Google's standard is to approve once a change clearly improves overall code health, even if it is imperfect. Changes should be small: about 100 lines is reasonable, 1000 is too large, and the SWE book says about 200. Reviewers should respond within one business day, and usually one reviewer is enough. Apple has published no equivalent guidance.

### Cited Findings
- Senior principle, quoted: "reviewers should favor approving a CL once it is in a state where it definitely improves the overall code health of the system … even if the CL isn't perfect." Also, there is "no such thing as 'perfect' code—there is only *better* code" — [eng-practices: Standard of code review](https://google.github.io/eng-practices/review/reviewer/standard.html)
- Rules: "Technical facts and data overrule opinions and personal preferences." The style guide is the absolute authority on style. Design choices rest on engineering principles, not preference. Prefix optional polish comments with "Nit:". For conflicts, seek consensus first, then escalate to the tech lead or maintainer, and do not let a CL stall — [eng-practices: Standard](https://google.github.io/eng-practices/review/reviewer/standard.html)
- What reviewers check: design, functionality (for both end users and future developers), complexity (including no over-engineering or speculative features), tests, naming, comments (explain *why*), style, consistency, documentation, every line, context, and good things (praise good work). The summary checklist also includes "sensible UI changes" and "safe parallel programming" — [eng-practices: What to look for](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
- Speed, quoted: "One business day is the maximum time it should take to respond to a code review request." Do not interrupt focused work to review; wait for a natural break. "LGTM with comments" is allowed for minor or non-mandatory points, which helps across time zones. For huge CLs, ask for a split into stacked smaller CLs — [eng-practices: Speed](https://google.github.io/eng-practices/review/reviewer/speed.html)
- Small CLs: "100 lines is usually a reasonable size for a CL, and 1000 lines is usually too large." File spread matters too: "A 200-line change in one file might be okay, but spread across 50 files it would usually be too large." Keep refactorings in separate CLs from features and bug fixes. Tests go in the same CL as the logic they cover. To split work, stack CLs, split by files or reviewers, split horizontally by layer with stubs, or split vertically by feature slice — [eng-practices: Small CLs](https://google.github.io/eng-practices/review/developer/small-cls.html)
- Approval bits at Google: (1) **LGTM**, a correctness and comprehension check; (2) **OWNERS** approval for that part of the codebase; (3) **Readability** approval, meaning conformance to the language's style and best practices. "Most reviews have one person assuming all three roles" — [SWE book ch. 9 Code Review](https://abseil.io/resources/swe-book/html/ch09.html)
- Numbers: small changes "should generally be limited to about 200 lines of code"; initial feedback is expected "within about a day"; "About 35% of the changes at Google are to a single file"; "Most code reviews at Google are reviewed by precisely one reviewer"; "the most important LGTM is the first one" — [SWE book ch. 9](https://abseil.io/resources/swe-book/html/ch09.html)
- The two Google sources give different size guidance (100 vs. 200 lines). Both are rules of thumb — [eng-practices](https://google.github.io/eng-practices/review/developer/small-cls.html) vs. [SWE book ch. 9](https://abseil.io/resources/swe-book/html/ch09.html)

### Inferences
- For a 2–3 person team: require 1 approving review per PR (the owner and reviewer can be the same person), respond within 1 business day, aim for PRs of 200 lines or fewer excluding generated files and lockfiles, keep refactor PRs separate, and include tests in the same PR. Replace "readability" with automated lint and format gates (ESLint/Prettier for the web-app, ruff/black for the Python services).
- For a solo developer, a self-review against the "what to look for" list plus CI gates is a reasonable substitute. An AI or peer review on risky PRs is optional.

### Gaps
- **Apple:** I found no public primary source on Apple's internal code-review rules. Treat any claims about them as unverified.

## 3. Testing at Google

### Takeaway
Google classifies tests by **size**, meaning the resources they may use, which is a separate axis from **scope**. The SWE book targets about 80% unit, 15% integration and 5% E2E tests. The widely quoted "70/20/10" comes from the 2015 Testing Blog era, but the post itself only says to keep a pyramid shape. Flakiness is treated as a first-class problem: 1.5% of test runs were flaky in 2016, and flaky tests are auto-quarantined.

### Cited Findings
- Test sizes: **Small** tests run in a single process, often a single thread, with no I/O, network, sleep or external resources. **Medium** tests run on a single machine, may use multiple processes and threads, and may make blocking calls to `localhost` only. **Large** tests drop the localhost restriction and can span machines. Size and scope (unit/integration/E2E) are separate concepts — [SWE book ch. 11 Testing Overview](https://abseil.io/resources/swe-book/html/ch11.html)
- Target mix, quoted: "80% of our tests being narrow-scoped unit tests … 15% medium-scoped integration tests … and 5% end-to-end tests" — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- "Just Say No to More End-to-End Tests" (Mike Wacker, Apr 22, 2015) argues that E2E tests are slow, flaky and hard to debug, and that suites should "retain that pyramid shape". The **70/20/10** split is widely credited to this post, but the page text I fetched did not state it explicitly, so treat the ratio as **unverified in the primary text** — [Google Testing Blog](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html). The attribution appears in secondary sources such as [Medium, Yash Batra](https://medium.com/@yashbatra11111/the-testing-pyramid-why-70-unit-20-integration-10-e2e-still-wins-fb25df39c18c).
- Newer framing: "SMURF: Beyond the Test Pyramid" (Adam Bender, Oct 15, 2024) — [Google Testing Blog](https://testing.googleblog.com/2024/10/smurf-beyond-test-pyramid.html). The body did not render in my fetch, so I have not verified the acronym's expansion (commonly given as Speed, Maintainability, Utilization, Reliability, Fidelity).
- Beyoncé Rule, quoted: "If you liked it, then you shoulda put a test on it." Test anything you don't want to break, including performance, correctness, accessibility, security and failure handling — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Testing on the Toilet started in April 2006. Each episode is one page, and it is Google's longest-running testing initiative. "Test Certified" (2005–2015) had five levels, each achievable within a quarter, and was used by 1,500+ projects — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Coverage, quoted: "Code coverage only measures that a line was invoked, not what happened as a result." Do not treat a coverage percentage as the goal — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Flakiness per the SWE book: tests start losing value at about 1% flakiness, and Google's flaky rate hovers around 0.15%, which still means thousands of flakes a day — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Flakiness per John Micco (May 27, 2016): **1.5% of all test runs** report a flaky result; **about 16% of tests** have some flakiness; **84% of pass→fail transitions** involve a flaky test. Mitigations were re-running only failing tests, marking tests flaky so a failure is reported only after **3 failures in a row**, an automated tool that quarantines overly flaky tests out of the critical path and files bugs, and a dedicated flakiness team — [googblogs mirror of Google Testing Blog](https://www.googblogs.com/flaky-tests-at-google-and-how-we-mitigate-them/) (original: [testing.googleblog.com](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html); that fetch did not return the numbers, but the mirror did). The two sources disagree: the SWE book's "0.15%" differs from the blog's "1.5%" by 10x. They may measure different things, or one may be a transcription error; this is unresolved.
- Larger tests exist for **fidelity**. Unit tests miss unfaithful doubles, config problems ("the number one reason for our major outages"), load problems and emergent behavior. Google's larger-test types are functional, browser and device, performance/load, deployment-config smoke tests, exploratory, A/B diff regression, UAT, probers and canary analysis, disaster recovery and chaos, and user evaluation (dogfooding, experiments, rater evaluation). Large-test timeouts run from 15 minutes to 1 hour. Larger tests suffer from flakiness and unclear ownership; the fixes are OWNERS files and per-test owner annotations — [SWE book ch. 14 Larger Testing](https://abseil.io/resources/swe-book/html/ch14.html)
- Speed-up advice: replace sleeps with event waits, shorten timeouts, split large tests, and use prebuilt binaries for non-core dependencies — [SWE book ch. 14](https://abseil.io/resources/swe-book/html/ch14.html)

### Inferences
- For the traffic dashboard: many small tests (the pure TS map-color, geo and event-parsing functions, and the Python control strategies like ACAMP and the anomaly injector), some medium tests (API service against a local sim, event contract round-trips), and a handful of E2E browser tests covering the main flows (load dashboard, create anomaly, see the emergency corridor). A ratio between 80/15/5 and 70/20/10 is fine.
- Flake policy for a small team: auto-retry failed E2E tests at most once or twice and record the retries. Any test that flakes twice in a week is quarantined with an issue filed within a day. Use no `sleep`s in tests.
- Visual regression: A/B diff and browser/device testing are Google's analogues. Playwright screenshot comparisons of the map at fixed zoom and with fixed data are cheap to add. Mask animated or tile layers to avoid flakes.
- Accessibility belongs under the Beyoncé Rule: add an automated axe check in E2E tests.

### Gaps
- I found no primary Google source that documents screenshot-diff tooling in detail. The SWE book only names the categories.

## 4. Launch process: SRE launch coordination, canaries, flags, dogfooding

### Takeaway
At Google, a "launch" is any externally visible change, and there were about 70 a week at the time of the SRE book. Launches go through a checklist run by Launch Coordination Engineers, followed by gradual rollouts: canaries, then feature flags at 1–10%, then wider release.

### Cited Findings
- Definition, quoted: a launch is "any new code that introduces an externally visible change to an application". Google did about **70 launches per week** — [SRE book ch. 27 Reliable Product Launches at Scale](https://sre.google/sre-book/reliable-product-launches/)
- LCE role: a consulting team within SRE that audits products for reliability, liaises between teams, drives the technical side of a launch, gatekeeps and approves "safe" launches, and educates developers — [SRE book ch. 27](https://sre.google/sre-book/reliable-product-launches/)
- Checklist areas: architecture and dependencies; integration (DNS, load balancers, monitoring); capacity planning (launch spikes of "up to 15 times higher than initially estimated"); failure modes (single points of failure, a dependency being down); client behavior (exponential backoff, jitter, no synchronized requests); processes and automation; development process (version control, release branches); external dependencies; rollout planning. My fetch summary called this eight areas but listed nine, so check the count against the chapter before quoting it — [SRE book ch. 27](https://sre.google/sre-book/reliable-product-launches/)
- Rollouts: changes proceed "gradually, according to a defined process, with appropriate verification steps interspersed". Feature-flag frameworks roll changes out "to a few servers, users, entities, or datacenters" and then "gradually increase to a larger but limited group of users, usually between 1 and 10 percent" — [SRE book ch. 27](https://sre.google/sre-book/reliable-product-launches/)
- Canarying (SRE Workbook): run **only one canary at a time**. Match canary duration to release cadence, so a daily release cannot use a week-long canary. Evaluate at most about a dozen metrics, preferably SLIs such as HTTP status codes and latency; CPU alone is a poor signal. Break metrics down by canary vs. control. Example: a 5% canary with 20% errors produces only a "1% overall error rate". The release principles are reproducible builds, automated builds, automated tests, automated deployments, and small self-contained changes — [SRE Workbook: Canarying Releases](https://sre.google/workbook/canarying-releases/)
- Dogfooding and experiments are listed as larger-test types. Dogfooding means "Limited rollouts … making features in production available to a subset of users"; in an experiment, "a new behavior is made available as an experiment to a subset of users"; rater evaluation asks human raters to pick the better result — [SWE book ch. 14](https://abseil.io/resources/swe-book/html/ch14.html)
- In the GWS case study from 2005, adding tests cut emergency pushes by half within a year — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Google's formal launch tooling: "Ariane launches" with per-approver "Request Review" buttons, and launches appearing on a launch calendar, as documented for open-source releases — [Google Open Source: Getting Approval](https://opensource.google/documentation/reference/releasing/approval). I only saw this in search snippets and did not open the page, so it is **unverified detail**.

### Inferences
- For a student dashboard deployed as a web app: put new risky features (live-backend mode, the green corridor, the photoreal globe) behind a simple flag such as a query-param or env flag. Demo to teammates and the advisor first (dogfood), then the class or sponsor, then everyone. Keep a one-command rollback to the previous deploy.
- A one-page launch checklist adapted from the SRE areas: dependencies (tile provider, backend availability, and falling back to simulation), failure modes (backend down, websocket drop), client behavior (reconnect with exponential backoff and jitter), capacity (a demo-day spike), monitoring (console error logging), and a rollback plan.

### Gaps
- I did not fetch the full text of the SRE book's example checklist questions. The areas above come from a summarized fetch.

## 5. Apple: design-led process, dogfooding, HI reviews, betas

### Takeaway
Apple's public process information is mostly about external betas: the Apple Beta Software Program, AppleSeed for IT, and Feedback Assistant. It has also recently added accessibility disclosure through App Store Accessibility Nutrition Labels. Apple publishes little about its internal engineering process.

### Cited Findings
- The Apple Beta Software Program lets users test-drive pre-release iOS 27, iPadOS 27, macOS 27, tvOS 27, watchOS 27, HomePod Software 27 and AirPods firmware. Feedback goes through the **Feedback Assistant** app — [beta.apple.com](https://beta.apple.com/)
- AppleSeed for IT is for enterprise and education organizations with admin roles in Apple School Manager or Apple Business. An admin accepts the terms for each beta period. It provides pre-release iOS/iPadOS/macOS, "detailed testing plans and forum discussions", team feedback through Managed Apple Accounts, and deferral of beta updates on supervised devices — [Apple Platform Deployment guide](https://support.apple.com/guide/deployment/test-software-updates-appleseed-beta-program-depe8583cf10/web)
- Accessibility Nutrition Labels cover 9 features: VoiceOver, Voice Control, Larger Text (200%+), Dark Interface, Differentiate Without Color Alone, Sufficient Contrast, Reduced Motion, Captions and Audio Descriptions. An app may claim a feature only if users can complete **all common tasks** with it. Common tasks include the primary functionality, first launch, login, purchase and settings. Apple recommends a per-device accessibility testing matrix. Labels are **voluntary now** and will become **required for new app and update submissions** at an unannounced date — [App Store Connect Help](https://developer.apple.com/help/app-store-connect/manage-app-accessibility/overview-of-accessibility-nutrition-labels)

### Inferences
- The Nutrition Label criteria make a concrete accessibility acceptance test for a web dashboard. The core tasks would be: view the map and its status, inspect an intersection, create an anomaly, and follow an emergency. Each must be completable with a screen reader and keyboard, at 200% text, in dark mode, without relying on color alone (important for congestion color ramps), at sufficient contrast, and with reduced motion (important for the globe dive transition).

### Gaps
- **Unverified / not found:** I found no primary source for Apple's internal dogfooding practice, internal Human Interface design-review gates, or accessibility as an internal release requirement. These are commonly reported in press and interviews, but I did not open a citable source, so do not state them as fact.
- I did not verify how Apple Maps specifically is engineered or released.

## 6. Accessibility and privacy reviews as launch gates

### Takeaway
At Google, privacy review is documented as part of every product launch: the privacy team reviews design docs and code. Accessibility is framed as something to test (the Beyoncé Rule). At Apple, accessibility is becoming an App Store disclosure requirement.

### Cited Findings
- Google's privacy team reviews design docs and code at launch. Crypto specialists review launches with cryptography. The security team reviews security plans and consults for product teams — [Google Cloud security whitepaper](https://docs.cloud.google.com/docs/security/overview/whitepaper)
- Accessibility is named among the things to test under the Beyoncé Rule — [SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)
- Apple's accessibility labels will become mandatory for submissions — [App Store Connect Help](https://developer.apple.com/help/app-store-connect/manage-app-accessibility/overview-of-accessibility-nutrition-labels)

### Gaps
- I did not verify a public Google document that makes accessibility review an explicit launch-checklist gate. It is often asserted but not confirmed here. The same goes for legal review.

## 7. What a 1–3 person capstone team should adopt

### Takeaway
Adopt lightweight versions of each practice: mini design docs, small PRs with one reviewer, a test pyramid with flake quarantine, CI gates, a launch checklist, and flagged rollouts with dogfooding. Every item below is derived from the cited findings above.

### Cited Findings
- (Everything here is derived from the sources cited in sections 1–6. No new facts.)

### Inferences
**Mini design doc template (1–3 pages; after [Ubl](https://www.industrialempathy.com/posts/design-docs-at-google/))**
1. Context and scope (5–10 lines)
2. Goals / Non-goals (bullets)
3. Design (a diagram, the data flow and event contracts, the key trade-offs)
4. Alternatives considered (2–3, each with its reason for rejection)
5. Cross-cutting concerns: privacy (camera/vision data), security, observability, accessibility, failure modes and fallback
6. Test plan and rollout plan. These two sections are an addition beyond Ubl's five, drawing on the SRE and SWE-book practices.
Reviewers are the other teammates plus the advisor. Allow 2–3 days, then update the doc if the implementation diverges.

**PR checklist (after [eng-practices](https://google.github.io/eng-practices/review/reviewer/looking-for.html))**
- [ ] One concern per PR; about 200 changed lines or fewer (excluding lockfiles and generated files); refactors kept separate
- [ ] Tests added or updated in the same PR for any logic change
- [ ] Design fits the architecture; nothing speculative or over-engineered
- [ ] Clear names; comments explain *why*
- [ ] README/docs updated if behavior or the interface changed
- [ ] UI change: screenshot attached; keyboard- and contrast-checked; nothing conveyed by color alone; respects reduced motion
- [ ] Privacy and security: no secrets or API keys committed; no new personal data collected without a note
- Reviewer SLA: first response within 1 business day. Use "Nit:" for optional comments. "LGTM with comments" is fine for minor issues.

**CI quality gates (blocking)**
- Lint, format and typecheck (tsc, ESLint, ruff/mypy)
- Small and medium tests (the pytest suites for the sim, API and common services, plus the web-app unit tests)
- Event contract/schema compatibility checks
- A handful of Playwright E2E smoke tests covering the main flows, plus axe accessibility checks on the key pages
- Optional: screenshot diffs of the map with deterministic data and masked tile layers
- Build succeeds, and the bundle stays under a size budget
- Flake policy: at most 1 retry. A test that flakes repeatedly is quarantined and gets an issue ([Micco 2016](https://www.googblogs.com/flaky-tests-at-google-and-how-we-mitigate-them/)). Use coverage as a signal, not a target ([SWE book ch. 11](https://abseil.io/resources/swe-book/html/ch11.html)).

**Launch/demo checklist (after [SRE ch. 27](https://sre.google/sre-book/reliable-product-launches/) and [Workbook canarying](https://sre.google/workbook/canarying-releases/))**
- Dependencies and fallbacks: tile provider or API key down, backend unreachable, fallback to simulation mode
- Client behavior: reconnect with exponential backoff and jitter
- Capacity: a demo-day concurrency estimate, planned with generous headroom (Google saw spikes up to 15x its estimates)
- Rollout: feature flag, then team dogfood, then a small audience (the 1–10% analogue), then everyone. One canary at a time. Watch a few user-facing metrics: errors and latency.
- Rollback: a one-command redeploy of the last good build
- Accessibility pass on the common tasks, using criteria modeled on Apple's labels
- Privacy note: what data is collected or shown, especially camera/vision feeds

### Gaps
- Specific numeric thresholds for a student team (bundle-size budget, E2E count) are judgment calls, not sourced rules.
