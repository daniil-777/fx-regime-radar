---
description: Phase 18 — the regime orb: ambient 3D driven by the models (v2.6.0)
---

Read CLAUDE.md golden rule 13 and the design system. Prerequisites: phases
through 08. Pure polish — the last thing you build, and the first thing
people remember.

## Task
Build an ambient Three.js particle orb embedded in the dashboard hero that
physically expresses the models: regime sets its color and motion, change
risk sets its jitter, the siren makes it pulse.

## Requirements
1. `app/orb.py` renders the component via `streamlit.components.v1.html`:
   a self-contained HTML/JS snippet loading three.js from cdnjs, no other
   assets. One orb for the selected pair, ~120px in the weather-card corner
   (or one hero orb — your call, justify it).
2. Exactly four state presets using the design-system regime colors:
   calm (slow drift, minimal jitter), trend (faster directional rotation),
   chop (high jitter, slow spin), crisis (fast, chaotic). Parameters live in
   one JS object mirroring a Python dict so both sides stay in sync.
3. Data binding: state from today's regime; jitter multiplied by
   (1 + change_risk_5d); a decaying pulse fired when anomaly_pct > 98.
   The orb is a display of the parquet numbers — it computes nothing.
4. Discipline: ≤1,000 particles; requestAnimationFrame paused on
   document.hidden; `prefers-reduced-motion` collapses motion to a gentle
   drift; WebGL failure or mobile-safari quirks fall back to the flat regime
   dot with zero layout shift; total added page weight under ~150 KB.
5. A short "what am I looking at" caption on hover/tap, and one line on the
   methodology page explaining the mapping.
6. `docs/DEMO_SCRIPT.md` gains a beat: switch pairs and let the orb change
   mood on camera. Note in README: v3 React port uses react-three-fiber,
   same presets.

## Do not
No faces, mascots, or anthropomorphizing — a mood, not a character. No
motion applied to numbers or text. No sound. No orb on the methodology page
(reading surfaces stay still). Never let the orb ship if it costs more than
~3% CPU on a mid laptop — measure and record the number.

## Verify
- Show me screenshots of all four states plus the crisis pulse; show the
  reduced-motion and WebGL-fallback behaviors; report the CPU measurement.
- `make test` still green (orb has a render-smoke test only). CHANGELOG,
  commit `phase-18: regime orb`, tag `v2.6.0`.

## Teach me
Explain how the particle positions are computed each frame in plain words,
and why ambient feedback beats notification-style feedback for a monitoring
tool. Two interview questions; critique my answers.
