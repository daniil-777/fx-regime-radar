---
description: Phase 31 — trust-first UI: evolve the design system to the target mockup (next minor tag)
---

Read CLAUDE.md (design system section) and golden rule 8. Display layer
only — run any time after phase 20, ideally before phase 27. The visual
target ships with this phase: `design/design-target-mockup.html` — open it
in a browser and MATCH it, don't reinterpret it. This phase EVOLVES your
existing system (app/ui.py owns the look, one Plotly template — good bones,
keep the architecture) rather than replacing it.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: app/ui.py injects CSS once (Google Fonts Inter + JetBrains
Mono; card #131A26, border #232D3F; regime pills; one Plotly dark template);
.streamlit/config.toml carries the theme; CLAUDE.md defines the design
system; the phase-18 orb's JS preset object mirrors the Python palette;
public surfaces = proof page (20), weekly report (27), widget.js (24),
README hero. Verify, report drift, WAIT.

## Task
Migrate the design system to the mockup's tokens, add the two signature
structures (condition banner, trust strip), and apply one look to every
surface a user sees. Eye-catching here means credible: full market state
readable in 3 seconds — "instrument, not toy".

## Requirements
1. Tokens, single source `design/tokens.json` → generated CSS for app/ui.py,
   .streamlit/config.toml values, and the Plotly template: surfaces nimbus
   #0E1420 (app) / front #151D2E (cards) / line rgba(255,255,255,.08);
   text #E8ECF4 / #9AA6B8 / #5C6980; regime colors (data + status ONLY):
   calm #3ECF8E, trend #4DA3FF, chop #F5B942, crisis #FF5C5C; link/action
   accent beacon #7FD1C9; light variant for the email report. Update the
   CLAUDE.md design-system section to match — the constitution and the code
   must agree. UPDATE THE ORB'S JS PRESET COLORS to the new regime hexes
   (the mirrored dict is easy to forget).
2. Type at the existing Google Fonts import point: Space Grotesk (display —
   regime words, page titles only), IBM Plex Sans (UI/body), IBM Plex Mono
   for EVERY number, hash, and ledger value with tabular figures ('tnum'),
   numbers right-aligned in tables. No third family, no weights above 500.
3. Condition banner (signature; replaces the hero row's top): eyebrow with
   pair + "data through" date; the regime word huge in its color; one
   metrics line (change risk ± interval, siren); the quiet 90-day risk
   trace with shaded band; the consensus 3-dot module. Full state readable
   in 3 seconds from 2 meters.
4. Motion budget: the orb stays as the ONE ambient element (its
   reduced-motion and fallback rules already exist); the only other motion
   is the live dot's slow pulse. Nothing else moves — no third animation,
   ever.
5. Trust strip on every surface, never below the fold: forward-test day
   count, live Brier vs frozen, coverage vs target, chain-head short hash +
   check, "Verify independently" link. Mono.
6. Charts: regenerate the single Plotly template from tokens (transparent
   background, 6%-white gridlines, regime band shading, semantic colors
   only); audit and convert every existing figure, including phase-04/15/16
   report figures where they render in-app.
7. IA pass: nav Overview / Pairs / Treasury / Storms / Proof (Arcade and
   Strategy lab live under an Analysis group); every widget answers "what
   does the user decide with this?" or moves there; empty/loading/error
   states with directive copy — say what happened and what to do, never
   apologize, never vague.
8. Public surfaces from the same tokens: proof + weekly report HTML,
   widget.js badge (regime dot + word + siren), README hero screenshot and
   og-image regenerated.
9. Quality floor: contrast ≥ 4.5:1 for every text/surface pair (check chop
   and crisis on nimbus; adjust tone, never meaning); regime never
   color-only — word + dot; visible keyboard focus; responsive to 360px.
10. Enforcement: `make lint-ui` greps app/ and src/ for hardcoded hex
    outside tokens.json and fails on findings; add it to CI and note the
    rule in CLAUDE.md so every future phase obeys without being told.

## Do not
No framework migration. No gradients, glassmorphism, glow, or shadow soup.
No emoji as UI (your rule already). No new chart types (phase 19 owns 3D).
No third animation. No direction language. If anything competes with the
condition banner, quiet the element — never louden the banner.

## Verify
- Before/after screenshots: Overview, a pair page, Treasury, Proof, weekly
  report, widget — desktop and 375px; orb shown in all four states with the
  NEW colors.
- The 3-second glance test on me from one screenshot.
- Contrast report; reduced motion honored; all figures on the template;
  `make lint-ui` green; CLAUDE.md design section updated.
- CHANGELOG, commit `phase-31: trust-first ui`, next minor tag.

## Teach me
Why credibility out-attracts flash for a risk product; what tabular
numerals fix; data-ink in one paragraph; why one signature element beats
five. Quiz: (1) someone proposes animating the siren dial — accept or
decline, why? (2) which surface earns light mode and why? Critique my
answers.
