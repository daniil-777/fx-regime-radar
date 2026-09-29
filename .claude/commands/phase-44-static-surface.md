---
description: Phase 44 — the static customer surface: token-built pages on a CDN, PWA, enforced performance budgets, reversible cutover (next minor tag)
---

Read CLAUDE.md golden rules first. This phase does not rewrite the application. It
builds a second, static reader of the same artifacts — the surface a treasurer
actually touches — and leaves Streamlit in place as the analyst console it has
always been good at. Nothing is ported, because the golden rule that the app computes
nothing means there is no logic to port, only rendering. Both surfaces run in
parallel until the static one meets its budget, and the cutover is a DNS change that
undoes in minutes.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: `pipelines/run_daily.py` writes artifacts committed daily by the Action;
Streamlit `app/app.py` + `app/pages/` reads artifacts only; `design/tokens.json`
generates `docs/widget-tokens.css`; phase-38 eight render primitives and the 50-card
registry; phase-36 standalone avatar widget page; phase-40 answer packs with baked
audio; phase-43 provenance records, source strips, receipts; Rust axum on the Oracle
VM (record its shape, cores and RAM) with API keys, Prometheus, cost caps; docs/
already publishes the proof page and weekly report. Verify, report drift, WAIT.

## Task
Emit a small public state artifact, build the five customer pages as static
HTML/CSS/JS from the existing tokens and primitives to a professional visual
standard, host them on a CDN with the API remaining on the VM, make the result
installable and correct on real iOS and Android devices, enforce hard performance
budgets in CI, and cut over reversibly.

## Requirements

### A. The public state artifact
1. A final pipeline step writes `public/state.json`: per pair the regime, filtered
   probabilities, change risk with interval, siren, consensus, treasury summary, days
   to next events, ledger scoreboard, chain head, drift flag — plus `context_version`,
   `generated_at` and a schema version. Under 50 KB uncompressed; the build fails if
   it exceeds the cap.
2. No secrets, no API keys, no internal identifiers, no personal data, nothing from
   the research lab. A test asserts the file is safe to serve to the open internet,
   because it will be.
3. Published alongside the static site so a page needs exactly one fetch to render.
   Cache headers keyed to `context_version`.

### B. The pages, built to a professional visual standard
4. Five pages — Overview, Pairs, Treasury, Storms, Proof — plus the existing avatar
   widget, as plain HTML with CSS generated from `design/tokens.json` and the
   phase-38 primitives ported to vanilla JS. No framework, no bundler beyond
   minification, no Plotly. uPlot only where a plotted axis is genuinely required.
5. **The craft requirements, not negotiable:** the condition banner is the single
   signature element and everything else stays quiet around it; one display face
   (Space Grotesk) used only for regime words and page titles; IBM Plex Sans for UI
   and IBM Plex Mono with tabular figures for every number, right-aligned in tables;
   the 8px spacing grid; borders rather than shadows; regime colour used only for
   data and status, never decoration; a single accent for links and actions. The full
   market state must be readable in three seconds from two metres.
6. Motion budget unchanged: the ambient orb and the live dot, plus a ≤150 ms fade on
   card entry. Nothing else moves, ever.
7. States are designed, not accidental: empty, loading (skeletons at fixed heights so
   nothing reflows), stale (badge plus drift card), and error with directive copy
   that says what happened and what to do — never apologetic, never vague.
8. Critical CSS inlined; everything else deferred; all text renders before any script
   executes. A treasurer in a train tunnel still sees the condition banner.
9. Dynamic behaviour calls the Rust API: avatar session tokens, scenario pricing,
   alert preferences. Public pages need no auth at all.
9b. **Baked audio serving:** phase-40 pack audio publishes to the CDN beside
   `public/state.json`, immutable and keyed by `context_version`, with the ten
   most-served clips preloaded on first paint so a pack answer starts speaking without
   a fetch. Audio never streams through the VM.
9c. **The resolution echo** ("USDCHF, same reading —") renders as part of the answer in
   the same type as the answer, never as a separate system-looking line. It must read
   as speech, because it is.
10. Visual parity with the Streamlit surface at the token level; `make lint-ui` covers
    the static sources, so no hardcoded hex may enter.

### C. Mobile correctness, tested on real hardware
11. PWA: manifest, icons, theme colour, standalone display, and a service worker
    caching the shell and the last `state.json` so a cold open shows yesterday's
    reading with a clear stale badge rather than a blank screen.
12. iOS specifics: audio and microphone only after an explicit user gesture; test
    WebRTC on a real iPhone in Safari, not a simulator; check standalone-mode viewport
    insets so the banner is not under the notch.
13. Touch targets at least 44 CSS pixels — audit consensus dots, source chips and
    drill chips, currently sized for a mouse. Sheets and swipes for the board on small
    screens; no hover-only affordances anywhere.
14. Test matrix recorded in the PR: iOS Safari, Android Chrome, desktop Chrome and
    Safari, at 375 / 768 / 1440 px, on a throttled connection.

### D. Performance budgets, enforced not aspired to
15. Measured on a throttled mobile profile in CI, failing the build when exceeded:
    first contentful paint under 1.2 s; time-to-interactive under 2.0 s; total
    transferred bytes for Overview under 200 KB including the state artifact; zero
    cumulative layout shift; Lighthouse performance and accessibility both ≥ 90.
16. Record the same measurements once for the current Streamlit surface, for the
    comparison table in phase 45 — this is the evidence the change was worth making.

### E. Hosting split and cutover
17. The static site publishes to a CDN-backed host from the repository on each
    artifact commit. The Oracle VM serves only the API behind Caddy with automatic
    TLS. The proof page therefore stays reachable even if the VM is down — for a
    product whose promise is verifiability, that independence is the point.
18. CORS on the API restricted to the site origin; public read endpoints stay as they
    are.
19. Cutover is reversible: both surfaces live in parallel, the domain moves only once
    every budget in D passes, and the rollback is a DNS or redirect change documented
    in `docs/RUNBOOK.md` with an expected recovery time.
20. Streamlit remains deployed for the analyst console — arcade, strategy lab, stress
    lab, research lab, ops — behind authentication, linked from nowhere public. It is
    not migrated, restyled beyond tokens, or deprecated.

### F. Reliability basics
21. Health endpoint plus an external uptime check on the API, alerting on failure.
22. Backup and restore for the ledger, indices, answer packs and artifacts, with the
    restore executed once and timed.
23. Update `docs/CAPACITY.md` with what the VM carries after the static surface moves
    off it, and reclaim the freed memory for the phase-45 budget.

## Do not
Do not migrate or rewrite the Streamlit application. No JavaScript framework, no
bundler beyond minification, no Node server. No secrets, research content or personal
data in `public/state.json`. Do not serve the static site from the VM once the CDN
path works. Do not cut over before the budgets pass. No hover-only interactions, no
targets under 44 px, no second display typeface, no gradients or shadow soup, no
third animated element. Do not let the static and Streamlit surfaces drift visually —
both consume the same tokens.

## Verify
- `public/state.json` under the cap; the safe-to-publish test passes.
- All five pages plus the widget render correctly at 375 / 768 / 1440 px on the real
  device matrix; screenshots in the PR; the three-second glance test on me.
- Budgets enforced in CI and passing; before-and-after table against Streamlit on the
  same throttled profile.
- Installed to an iPhone home screen: opens standalone, condition banner under one
  second warm, yesterday's reading with a stale badge when offline.
- Avatar session starts from the static page on a real iPhone; gesture and audio
  behave; a phase-40 pack answer plays its baked audio.
- Proof page verified reachable with the VM deliberately stopped.
- Rollback rehearsed and timed; `docs/RUNBOOK.md` updated.
- `make lint-ui`, `make test` green; CI still ~5 minutes plus the budget check.
- CHANGELOG, commit `phase-44: static customer surface`, next minor tag.

## Teach me
Explain: why Streamlit's per-interaction server round trip makes it structurally
unsuited to a phone and why CSS cannot fix it; why an artifacts-only architecture made
this a build rather than a rewrite; why serving the proof page from a CDN rather than
the VM matters for this product specifically; what a budget enforced in CI protects
against that a one-off measurement does not. Quiz me: (1) Overview loads in 900 ms
warm but 3.4 s cold on 4G — name the three things to check, in order; (2) why does the
service worker show yesterday's reading with a badge rather than a blank screen, and
when would that be the wrong choice? Critique my answers.
