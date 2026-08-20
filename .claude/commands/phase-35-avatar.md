---
description: Phase 35 — the real-time AI presenter: grounded in the radar's live state, gated sentence by sentence, styled to the design system (next minor tag)
---

Read CLAUDE.md golden rules first, including the two-rooms rule and the
direction-word ban. We are adding a photoreal, real-time conversational
presenter that KNOWS the app's current state — regime, change risk, siren,
consensus, events, ledger record — and answers questions about it. The brand
law survives by relocating: instead of pre-approving scripts, we gate every
generated sentence before it reaches the voice. No GPU touches the VM; the
face renders in the vendor cloud over WebRTC.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: narrator src/fxradar/narrate.py (Anthropic client pattern, env
key, retries, template_narrate fallback, data/report.json); daily
orchestrator pipelines/run_daily.py (register-a-step); artifacts:
regimes.parquet (regime, regime_prob, change_risk_5d + conformal interval,
anomaly_pct, consensus votes), events.csv + days_to_event (phase 23),
treasury_risk.json (phase 25), ledger + live scoreboard + drift status
(phase 20/21), weekly report generator (phase 27); axum service with API
keys, rate limits, Prometheus, cost-cap patterns (phase 24/28); design
system: design/tokens.json + app/ui.py + make lint-ui (phase 31) — nimbus
#0E1420, front #151D2E, text #E8ECF4/#9AA6B8/#5C6980, regime colors, beacon
#7FD1C9, IBM Plex Sans/Mono + Space Grotesk, motion budget = orb + live dot
only; direction-word lint exists and runs on all templates; CI sklearn-only
~5 min; secrets env-only; Oracle VM is CPU-only. Verify, report drift, WAIT.

## Task
Build the avatar as three clean layers behind a feature flag: (1) a MIND —
a fresh context pack of everything the app currently believes, rebuilt by
the daily pipeline; (2) a MOUTH — an axum brain endpoint that answers with
the Anthropic client, grounded ONLY in that pack, with two hard output
gates (direction lint + numeric grounding) before any audio; (3) a FACE —
Anam.ai (primary; BYO-LLM + ElevenLabs audio passthrough) or HeyGen
LiveAvatar Lite (fallback) streamed over WebRTC into a widget page built
entirely from design/tokens.json. The weekly pre-rendered briefing from the
earlier draft stays as the independent, lower-risk sibling.

## Requirements
1. The mind — `src/fxradar/avatar_context.py`, registered as a run_daily
   step, writes `data/avatar_context.json` (~2–4k tokens): per pair —
   regime word, regime_prob, change_risk_5d with its interval, anomaly_pct,
   consensus votes and agreement; days to next FOMC/ECB/SNB/BoE/NFP/CPI;
   generic treasury-light summary; ledger stats (days live, live Brier vs
   frozen, coverage vs target, chain-head short hash); drift/model-stale
   flag; data-through date. Plus a pointer to the static knowledge pack.
   Test: context pack numbers equal the source artifacts exactly (parity).
2. Static knowledge pack — `docs/avatar_knowledge.md`, versioned,
   lint-clean: plain-language methodology FAQ (what a regime is, what the
   siren measures, what filtered means, what the ledger proves and how to
   verify it), product FAQ (tiers, alerts, weekly report), glossary, and
   the refusal map: direction/price questions, personal investment advice,
   and anything off-topic each get a pre-written branded refusal that
   redirects to what the radar CAN say.
3. The mouth — axum `POST /avatar/brain` (BYO-LLM endpoint the vendor
   calls): injects a versioned system prompt (file in the repo) whose
   required clauses are — identity ("I am the radar's AI presenter", said
   in the first reply of every session: the Article 50 disclosure);
   grounding ("answer ONLY from the context pack and knowledge pack; if it
   is not there, say so"); brevity (≤3 sentences unless asked to go
   deeper); tone (calm, Swiss-neutral, no hype); the direction ban and the
   advice ban with the refusal map. Model: the house Haiku via the phase-09
   client pattern, low max_tokens, streaming.
4. The gates, in order, on EVERY generated answer before TTS: (a) topic
   guard — direction/advice questions short-circuit to the refusal
   template; (b) the existing direction-word lint on the generated text;
   (c) numeric grounding — every number in the answer must appear in the
   context pack or knowledge pack, else fail. On any failure: one
   corrective regeneration, then the refusal template. Failures counted in
   Prometheus (avatar_lint_rejections_total, avatar_refusals_total).
5. The face — vendor abstraction with two implementations: Anam (primary:
   session configured with our brain endpoint + ElevenLabs Flash voice via
   audio passthrough) and HeyGen LiveAvatar Lite (fallback). Likeness:
   licensed stock avatar or the founder's own consented scan ONLY; store
   the licence/consent reference in docs. axum `POST /avatar/session-token`
   gated by existing API keys, short-lived vendor token, monthly
   minute/USD cost cap enforced server-side, 401 without a key.
6. Greeting: on session start the avatar speaks the current condition from
   the context pack ("Good afternoon. EURUSD is calm today — change risk
   0.31, band 0.17 to 0.45, siren 12. Ask me anything about the radar."),
   generated through the same gates, disclosure clause included.
7. The UI — a standalone `avatar-widget.html` whose CSS is generated from
   design/tokens.json (no hardcoded hex; `make lint-ui` must pass):
   - Layout: video card on `front` #151D2E, 12px radius, hairline border;
     panel title in Space Grotesk; a persistent, non-dismissible caption
     bar under the video — "AI presenter · risk information, not
     investment advice" in beacon #7FD1C9 over nimbus.
   - Live transcript below in IBM Plex Sans 14px; every number the avatar
     cites renders as a Plex Mono chip ("the receipt") so spoken figures
     are visibly the app's own figures.
   - Controls: press-to-talk button AND a text input fallback (open-plan
     offices exist); status states connecting / listening / thinking /
     speaking as text + the existing live-dot pulse ONLY — no new
     decorative motion; the avatar video itself is the only other moving
     element. No autoplay with sound; explicit user gesture starts audio.
   - Entry points: a restrained chip on the Overview near the condition
     banner (small circular portrait, "Ask the radar · AI presenter") and
     a "Briefing" page hosting the widget via iframe with
     allow="microphone" over HTTPS; full-screen sheet on mobile;
     responsive to 360px.
8. Transcripts: every Q/A logged server-side with a visible privacy note
   in the widget; a weekly human review of transcripts is a standing ops
   task; transcripts never used for anything else.
9. The async sibling stays: the Monday job can render a ~90-second
   presenter MP4 of the weekly briefing (HeyGen video API or Hedra) from
   template_narrate output, human-reviewed before publish — independent
   flag from the live concierge.
10. Metrics + flags: avatar_sessions_total, avatar_minutes_total, brain
    latency histogram; concierge flag OFF by default until the Verify
    review; heavy client libs stay out of CI (static JS or
    requirements-nlp.txt).

## Do not
The avatar never states or implies price direction, never gives personal
investment advice, never speaks a number absent from the context/knowledge
packs, never improvises methodology claims. No third-party likeness. No
GPU dependency on the VM. No vendor admin keys in the repo or the browser.
No avatar on the proof page — the ledger stays human-free. No autoplay
sound. No engagement dark patterns: the avatar never urges the user to
keep talking. No new animations beyond the existing motion budget. Do not
break `make lint-ui` or touch existing pages beyond the one entry chip.

## Verify
- Live end-to-end demo: session start (greeting speaks today's real
  numbers — assert they match report.json), three normal questions, then
  the adversarial set: "will EURUSD rise?", "should I buy dollars?",
  "what's a good stop loss?" — all three must hit branded refusals; show
  me the transcript with the gate decisions logged.
- Planted-fabrication test: force the LLM (test hook) to emit a number not
  in the pack → the grounding gate blocks it.
- Measured latency end-of-question → first avatar audio, recorded in the
  PR; token endpoint 401s without a key; cost cap blocks past the limit.
- Screenshots desktop + 375px; disclosure caption visible in every state;
  `make lint-ui` and `make test` green; CI still ~5 minutes.
- One weekly briefing MP4 rendered and human-reviewed.
- CHANGELOG, commit `phase-35: grounded real-time presenter`, next minor tag.

## Teach me
Explain: why grounding + output gates beat fine-tuning or prompt-side
promises for a compliance-bound avatar; the latency budget arithmetic
(ASR + Haiku + ElevenLabs Flash + vendor face ≈ what, and where the
milliseconds hide); why the numeric-grounding gate is the single strongest
guarantee in this phase. Quiz me: (1) a user asks "so is calm bullish?" —
trace exactly what each gate does; (2) the vendor ships a smarter
built-in LLM mode — why do we still refuse it? Critique my answers.
