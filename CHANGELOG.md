# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

## v2.29.0 — speech that waits for you to finish, and hears accents (2026-08-20)

- One turn, one question. The recogniser fires a "final" result at every pause, so a multi-sentence
  question used to arrive as several truncated ones. Segments now accumulate into a turn and are
  sent only after 1.8 s of real silence — measured from the live audio level, not the recogniser's
  impatience — with ceilings (45 s, 700 chars) so a hot mic cannot run away, and stopping the
  conversation mid-thought sends what you already said rather than discarding it. Verified in-page:
  two sentences separated by a pause arrive as ONE question.
- Accented English gets a domain-aware second chance: `maxAlternatives = 5`, and the alternative
  mentioning things this app actually talks about wins (siren, regime, change risk, ledger, the
  currency and pair names); ties keep the engine's own confidence order. A fixup table then repairs
  the mishearings these terms attract ("sirene" → siren, "bit coin" → bitcoin, "rubble" → ruble,
  spelled-out "e u r u s d" → EURUSD).
- An accent field ("Your English") picks the recogniser locale — US, UK, India, Australia, Canada,
  Ireland, New Zealand, South Africa, Singapore, or match-my-browser — remembered in localStorage
  and applied to a live conversation without restarting it.
- Her speaking clock no longer caps at 20 s, so long answers hold the speaking state (and its
  click-to-skip) for their real duration.
- NEW GATE, from a real incident this session: an edit inserted a statement into an async function
  ("async const ..."), which broke the WHOLE widget script — every function undefined — while the
  page still served 200 and screenshotted fine. `tests/test_widget_js.py` now parses the inline
  widget JavaScript with `node --check` and asserts the voice contract's symbols exist. This class
  of failure can no longer ship silently.
- A taken vendor slot reported as "unknown error" now gets the same plain recovery steps as the
  explicit concurrency error (single-session plans report it both ways).
- 302 python (+3) + 56 rust tests green; clippy and `make lint-ui` clean.

## v2.28.2 — a real voice-conversation control that never scrolls away (2026-08-20)

- The control disappeared as soon as the transcript grew, and the cause was one inline style:
  `#session.style.display = "block"` overrode the stylesheet's flex column, so the card could not
  size itself and the controls overflowed the iframe. Measured before: the button sat at y=1526 in
  an 820 px frame — unreachable. The card is now a genuine flex column (transcript scrolls, stage
  capped at 42vh, controls pinned), verified with a full transcript at 560×820 and 390×780: the
  control is on screen in both.
- The round mic icon becomes a proper voice-conversation pill: full width, mic glyph, an explicit
  state label ("Start voice conversation" ↔ "Listening — tap to stop"), and a five-bar level meter
  INSIDE the button driven by the real input spectrum (five frequency bands, flat when silent).
  It is honest feedback rather than ambience — the bars only exist while the user has the
  conversation on, and flat bars are themselves the diagnostic. Text input keeps its own row
  beneath, always available.
- Briefing iframe grown to 820 px and its caption now names the browser requirement; widget copy
  updated to match the new control ("voice conversation", not "the mic button").
- 299 python + 56 rust tests green; clippy and `make lint-ui` clean.

## v2.28.1 — the mic tells you the truth (2026-08-20)

- Found the real reason the microphone "did nothing", by feeding a spoken WAV into Chrome as a real
  microphone: with `llmId: CUSTOMER_CLIENT_V1` — the BYO-brain mode that makes our gates the only
  voice — Anam performs **no speech recognition at all**. No vendor transcript can ever arrive, so
  the browser's Web Speech API is the ear (already added in v2.28.0, now the documented primary).
  Probed and recorded in docs/AVATAR.md; Web Speech verified to start both standalone and inside
  the Briefing iframe, so the iframe was never the blocker.
- `/avatar` is now served `Cache-Control: no-store`. It had NO cache headers, so Chrome reused the
  old script against a new server — which is how a fixed mic kept looking broken (the new greeting
  came from the server, the old JavaScript from the disk cache).
- The mic is now observable instead of mysterious: a live input-level meter (our own getUserMedia +
  AudioContext, moving only while the toggle is on — interaction, not ambience) proves the
  microphone works even when recognition fails, and after 12 s of silence the presenter says which
  half failed, in plain words, naming the recogniser error.
- Voice barge-in no longer depends on the vendor's detector: interim browser-recognition text
  interrupts her directly.
- An audio-ready gate: if the WebRTC audio track never lands, she falls back to an audible voice and
  says so, instead of miming a greeting nobody hears.
- Methodology questions are answered, not refused: 8 new knowledge-pack entries (methodology
  overview, end-to-end pipeline, model inventory, look-ahead-bias discipline, market coverage,
  how to verify the numbers, the hedge-ratio table, who built it and why) — 22 FAQ entries, all
  lint-gated at build. "What is methodology?" now answers keylessly.
- 299 python + 56 rust tests green; clippy clean; `make lint-ui` clean.

## v2.28.0 — the presenter knows every market, and you can interrupt her (2026-08-20)

- Barge-in: the user always outranks the presenter. While she speaks the status line reads
  "speaking — click to skip" (one click stops her, `interruptPersona()` on the vendor); typing or
  sending interrupts and asks; with the mic on, starting to speak interrupts (the vendor's
  echo-cancelled voice-activity event). ElevenLabs playback resolves on pause so an interrupt never
  wedges the input.
- Two ears, one mouth: in photoreal mode the browser's own speech recognition now runs BESIDE the
  vendor's ASR — whichever hears a phrase first wins, near-duplicates within 5 s drop, interim
  text shows live as "heard: …" so a working mic is visible. One dead pipeline no longer means a
  dead conversation.
- The whole map in the mind: `data/avatar_context.json` gains `markets` — every universe
  (FX majors, G10, EM, crypto), per pair the regime + probability + days-in, change risk with its
  band, siren, consensus — 23 markets, all inside the grounding gate's closed number set by the
  existing recursive walk. The greeting names the count.
- Keyless market answers: a deterministic lookup in the Rust brain (pair codes, bare legs,
  currency words — "yen", "bitcoin", "ruble"; single-currency questions resolve to the dollar
  cross) answers from the pack by template before the FAQ — grounded by construction, no LLM
  needed. With ANTHROPIC_API_KEY set the LLM path sees the same markets in CONTEXT.
- 299 python + 56 rust tests green; clippy -D warnings clean; verified in the live widget over
  real WebRTC: greeting skippable mid-word, mic granted, crypto question answered, zero console
  errors.

## v2.27.0 — decision support + a voice path that explains itself (2026-08-20)

- Personal hedging decision support, computed — never generated (owner decision 2026-08-20,
  CLAUDE.md rule 4 amended): `src/fxradar/decision.py` derives a deterministic hedge ratio from the
  treasury light (hedge 0.75 / ladder 0.50 / wait 0.25), risk tolerance ±0.15, consensus ≥2/3
  +0.05, clipped to [0.10, 0.95] in 5 % steps, with tranche schedules and the ES of the uncovered
  remainder as the price tag; the daily pipeline writes `data/decision_table.json` (a `decision`
  stage after `avatar`). The Rust brain answers hedge questions from that table by TEMPLATE —
  parse pair/amount/currency/horizon/tolerance, arithmetic on the user's stated amount, disclosure
  prefix on the first advice answer of a session, direction lint still blocking — the LLM never
  writes advice. Flag `FXRADAR_AVATAR_ADVICE` (default OFF); `source: "decision"` in the widget
  meta. Swiss FinSA review required before offering to clients (compliance note in the artifact).
- The voice path now explains itself instead of failing silently — the real fix for "I press the
  mic and hear nothing": (a) `talk()` failures fall back to audible TTS instead of returning into
  silence; (b) the greeting waits for the vendor session's SESSION_READY before speaking (talk()
  before WebRTC is ready was simply lost); (c) the SDK's mic-permission events and
  `getInputAudioState()` surface the true mic state in the mic note, and a blocked mic says how to
  unblock it; (d) an autoplay-blocked voice gets an explicit "Enable sound" button; (e) the Anam
  one-session concurrency limit — the silent killer: a stale tab holds the only slot and attach
  dies — now produces a plain-language message with the recovery steps, and `pagehide` releases
  the slot by stopping the stream; (f) spoken questions queue behind her speech instead of being
  dropped. Verified headless over real WebRTC: 1 audio track, unmuted, mic granted, zero console
  errors.
- 299 python + 54 rust tests green; `make lint-ui` clean.

## v2.26.3 — live voice conversation (2026-08-20)

- One tap to talk: the hold-to-talk emoji button becomes a proper conversation toggle — an SVG mic
  (no emoji as UI), beacon ring + the single sanctioned pulse while live, and a mic-status line that
  says plainly when the microphone is streaming. Vendor mode: the persona's own speech recognition
  hears you continuously over WebRTC; her transcripts route through the gated brain only while the
  toggle is on, and sessions start MUTED (privacy by default — her ears open only with the button).
  Local mode: a continuous browser-recognition loop with permission-denied handling.
- Fix that made voice possible at all inside the app: the Briefing page's iframe is now hand-rolled
  with `allow="microphone; autoplay"` — Streamlit's iframe helper cannot grant mic permission, which
  silently killed voice in the embedded widget.

## v2.26.2 — fix: vendor sessions carry two tokens (2026-08-20)

- Bug found in live use: in Anam mode the widget presented the VENDOR's session token to OUR
  `/avatar/brain`, which rightly rejected it → 401, dead questions, no voice. Vendor session
  responses now also mint our own 30-minute `brain_token` (same store as local sessions); the
  widget uses the vendor token for the WebRTC face and the brain token for brain/tts. New contract
  test; friendlier expiry message in the widget. Verified live end-to-end: question → gated answer
  (`gate pass · 5 ms`) → spoken by the photoreal persona.

## v2.26.1 — the photoreal face is live (2026-08-20)

- Anam integration VERIFIED LIVE with a real key: fixed the session payload to `llmId =
  CUSTOMER_CLIENT_V1` (the critical bit — it switches the vendor's own brain OFF, so the persona
  speaks only what our gated `/avatar/brain` returns via `talk()`; the earlier `brainType` field
  would have let their LLM answer around our gates), stock persona Cara + voice configurable via
  `FXRADAR_AVATAR_ANAM_*` envs, likeness reference recorded in docs/AVATAR.md. Widget: SDK pinned
  to `@latest` (there is no v2), persona speech transcripts routed through our brain via
  `MESSAGE_HISTORY_UPDATED`. Dev waiver now covers non-local vendors too (the widget never holds an
  API key; production keeps the key gate — test updated: keyless anam in dev → 503 not-configured,
  not 401). Screenshot tool grants fake media so WebRTC widgets can be captured headless.
  Live proof: 1152×768 WebRTC stream playing in the widget, greeting spoken through the persona.

## v2.26.0 — the presenter opens up: studio voice, photoreal wiring, open conversation (2026-08-20)

- **Open conversation** (`FXRADAR_AVATAR_OPEN=1`, the `make avatar` default): the presenter answers
  ANY topic with the conversational v2 system prompt — app-state numbers still come only from the
  pack; general-knowledge numbers are allowed and the grounding gate becomes annotate-only
  (`open:ungrounded` badge, still counted). The two constitutional bans stay hard in every mode:
  never price direction, never personal advice (verified live: a planted "bullish" still blocks in
  open mode while "Bretton Woods ended in 1971" passes annotated).
- **Studio voice**: `POST /avatar/tts` — ElevenLabs Flash v2.5 when `ELEVENLABS_API_KEY` is set,
  monthly character cap, and a hash gate so the server only voices answers OUR gates produced
  (403 for anything else — the TTS cannot be used to speak ungated text; verified live). Keyless →
  404 and the widget falls back to the browser voice.
- **Photoreal face wiring**: vendor `anam` sessions attach the Anam JS SDK stream to the widget's
  video and speak gated answers via the vendor voice; the drawn presenter (now with catchlights and
  a resting smile) remains the keyless face and the reduced-motion fallback.
- `make avatar` resolves ANTHROPIC / ELEVENLABS / ANAM keys from the environment or
  `.streamlit/secrets.toml`, prints what's on/off, and picks the anam vendor automatically when its
  key exists. docs/AVATAR.md: the three keys, one table. 50 rust tests.

## v2.25.1 — the presenter gets a face + one-command demo (2026-08-20)

- The keyless FACE is now a drawn presenter: a geometric bust in the token palette — blinking eyes,
  a mouth that animates while speaking, brows, collar, a beacon-teal headset with mic boom, and a
  regime-coloured ring that wears today's lead regime. Pure SVG, tokens only (tested), deliberately
  non-photoreal (no likeness questions; the spoken disclosure still opens every session), honours
  prefers-reduced-motion, and occupies exactly the slot a vendor's photoreal WebRTC video replaces.
- `make avatar` starts the presenter in one command (dev mode); the Briefing page auto-discovers a
  presenter on localhost when FXRADAR_AVATAR_URL is unset. TTS stall can no longer lock the input
  (onend/onerror/timeout all release it).

## v2.25.0 — phase 35: the grounded real-time presenter (2026-08-20)

- MIND — `fxradar.avatar_context` (daily stage): `data/avatar_context.json` with per-pair regime /
  change risk + band / siren / consensus, next scheduled events, treasury lights, ledger stats,
  drift flag, the pre-gated greeting (disclosure first — EU AI Act Art. 50), the refusal texts, the
  knowledge-pack FAQ, and `allowed_numbers` — the closed set of numeric tokens the presenter may
  ever speak (canonical form shared with the rust gate). Parity-tested against the source
  artifacts; every spoken template passes the rule-5 lint at build time (the pack refuses to exist
  otherwise — tested).
- KNOWLEDGE — `docs/avatar_knowledge.md` v1: methodology FAQ, product FAQ, glossary, refusal map;
  all answers are spoken templates, lint-checked.
- MOUTH — rust `/avatar/brain` (BYO-LLM endpoint): topic guard → answer (Haiku ≤220 tokens with the
  versioned system prompt `prompts/avatar_system_v1.txt`, or the keyless FAQ matcher) → direction
  lint → numeric grounding (question-echoed numbers allowed) → one corrective regeneration → the
  `not_in_pack` refusal. `GET /avatar/greeting`; `POST /avatar/session-token` (API-key gated,
  vendors anam/heygen/local, short-lived session tokens, monthly session/minute cost caps, dev
  flag); transcripts to sqlite with gate + latency; Prometheus avatar_* metrics; utoipa docs;
  feature flag `FXRADAR_AVATAR` off by default. Startup gate untouched.
- FACE — `/avatar` widget from the design tokens (tested ⊆ tokens.json): vendor video over WebRTC
  when configured, else the regime-coloured presenter disc + browser TTS/ASR — real-time, keyless;
  press-to-talk AND text input; permanent disclosure caption; every spoken number renders as a mono
  chip (the receipt); explicit user gesture before any audio; states as text + the one live-dot
  pulse. Streamlit **Briefing** page hosts it (empty state when not deployed); one restrained chip
  on the Overview. Async sibling `scripts/render_briefing.py` (independent flag, script always
  lint-gated, MP4 human-reviewed; keyless it stops at the reviewed script).
- Policy in `docs/AVATAR.md`: likeness = licensed stock or consented scan only (reference recorded
  before any vendor face), transcripts privacy + weekly human review, latency budget, no presenter
  on the Proof page, no autoplay, no engagement mechanics.

## v2.24.0 — phase 32: a choice of models (2026-08-19)

- App page **Model lab** (Analysis): segmented control over the three regime lenses + market
  select — price with bands under the chosen lens, a three-lens heatmap strip (weekly-majority tint
  for flickery lenses, true counts in the table), per-model anatomy with champion agreement, and the
  forecaster-engine scoreboard. Reads `data/model_lab.parquet` + `model_lab.json` written by
  `make model-lab` (rule 8: the page computes nothing); ships with the honesty framing — the record
  always runs on the champion.

- `fxradar.regime_models` — one contract, three regime models: the champion **HMM** (delegated
  byte-identically), the **statistical jump model** (Bemporad 2018; Nystrup et al. 2020/21;
  Aydınhan–Kolm–Mulvey–Shu 2024) fitted by coordinate descent (DP over the train sequence ↔ centre
  updates) with **greedy online** causal inference and λ chosen on train by matching the champion's
  switching rate, and a **GMM** persistence ablation. Same REGIME_COLUMNS output, same frozen naming
  rule, train-only scalers, bit-for-bit truncation invariance (tested). Selected per universe via
  `FXRADAR_REGIME_MODEL`; **fx hard-locked to the champion** (wall + public ledger — enforced and
  tested); an alternative runs under its own model_version → new ledger segment, never laundering.
- `fxradar.forecaster_models` — engines xgb (champion path, verbatim) / histgb (sklearn
  HistGradientBoosting, val-selected tree count over an explicit grid — no random
  validation_fraction) / logistic, all under the champion's exact protocol (Platt on val,
  recall-targeted threshold, frozen test once). No production env switch by design: promotion goes
  through the challenger-ledger protocol.
- `fxradar.model_lab` (`make model-lab`) — races everything, writes `reports/model_lab.md` +
  timelines png. fx results: jump at matched train persistence → OOS 1.7–8.8 switches/yr and mean
  runs up to 139 d vs HMM's 10–14 / 18–76 d, vol anatomy intact, but its crisis state nearly empty
  OOS (honest trade-off; HMM stays champion, jump is the named candidate for the next refit); GMM
  flickers 35–88 switches/yr; forecasters xgb 0.548 ≈ histgb 0.546 ≫ logistic 0.433 test PR-AUC.
- run_daily `stage_hmm` goes through the registry (default = champion, byte-identical delegation;
  regression-tested); `stage_advisor` falls back to empirical self-transition rates when the regime
  model has no transition matrix. 7 new tests.

## v2.23.1 — honest motion: the "now" pulse and bar replay (2026-08-19)

- Decision, recorded in CLAUDE.md: the main curve never vibrates — a daily-data product may not
  fabricate intraday motion, and ambient chart motion is false urgency (rule 13). The professional
  equivalents instead:
- The condition banner's 90-day risk trace ends in a pulsing "now" point sharing the live dot's one
  heartbeat (same keyframe — the motion-budget test still counts exactly one; reduced-motion safe).
- Pairs: **bar replay** behind an off-by-default toggle — the last ~250 trading days draw in via
  native Plotly frames (2 days/frame, ≤ 125 frames), the moving point wearing the filtered regime of
  its day, play/pause buttons, ending exactly on the as-of day. User-initiated interaction, never
  ambience; works in the time machine and for every universe.

## v2.23.0 — EM majors universe, with the ruble flagged honestly (2026-08-19)

- New universe **`em`** — USD/MXN, USD/BRL, USD/ZAR, USD/PLN, USD/RUB: the free-floating EM majors
  with clean Yahoo daily data, plus the requested ruble, added with its caveats in the record rather
  than hidden: corridor-managed until Nov 2014 (inside train), free float 2015–21, sanctioned
  onshore-only market since 2022; RUB=X is an offshore indicative series (17 % stale days in 2024
  after MOEX halted USD trading; a 5.0 bad print in 2023 caught by the cleaning rules); no ECB
  cross-check exists since March 2022; the narrator says "indicative offshore data". Known artefact,
  documented: RUB's calm training days come from the corridor era, so the siren saturates (> 98 most
  post-2014 days) — regime + change risk are the useful signals for this pair.
- Trained from scratch through `train-universe` (same splits as fx; EM cost model 3 bp + 120 × vol;
  bad-tick thresholds sized for 4–5 % EM days). Frozen test PR-AUC 0.548 vs 0.471 logistic vs 0.216
  base, Brier 0.135 vs 0.172, n = 9,867. Honesty checks: the Dec-2014 ruble crisis and the 2022
  invasion pin the siren at 100 (ranks 35 and 391 of ~5,500 days); 2022 is 80 % crisis-labelled;
  strategies stay negative net of EM costs (breakeven 0.00–0.15×). Own ledger under `data/em/`;
  daily Action runs all four universes; every app page renders under `em` (tested).

## v2.22.0 — ten FX pairs (G10 universe) + five crypto majors (2026-08-19)

- New universe **`g10`** — EUR/USD, USD/JPY, GBP/USD, USD/CAD, AUD/USD, USD/CHF, NZD/USD, EUR/GBP,
  EUR/JPY, USD/SEK: the ten most important free-floating pairs by BIS April-2025 turnover; managed
  floats / pegs (CNY, HKD, SGD, INR) excluded by design; EUR/CHF tried and rejected by the data (the
  2011–15 floor makes a training state singular) — it remains a context series. Trained from scratch
  through the existing `train-universe` path (same splits, cleaning and cost model as `fx`); frozen
  test PR-AUC 0.551 / Brier 0.110 on n = 19,746; validation, siren audit, strategies, stress and the
  3-D landscapes built; daily Action refreshes it; own ledger under `data/g10/`. The `fx` universe
  (bundle, goldens, Rust, ledger) is byte-identical.
- **Crypto majors** redefined: BTC, ETH, XRP, BNB, ADA (top non-stablecoins with ≥ 3 years of
  pre-split history; SOL deferred, LTC retired); history from 2017-11-09 so every pair's cross-pair
  correlation is defined; refit under `hmm 0.4.1` → the crypto ledger keeps the old three-coin rows
  as a closed segment and starts a new one. Frozen test PR-AUC 0.574 / Brier 0.110 on n = 6,579.
- Pipeline: FX-only stages (calendar, challenger, treasury) wrapped in `fx_only` so non-FX universes
  skip them with one log line — this also FIXES a regression where the crypto daily run failed on the
  phase-23 stage. `siren` audit plot draws one panel per pair (was hard-wired to three).
- App: `ui.grid` rows for card layouts, a dense `ui.market_table` for universes with more than four
  markets (Overview), a select instead of a wrapping tab row for > 5 markets, calendar and treasury
  fallbacks for FX universes; universe tests for G10/crypto; daily.yml runs all three universes.

## v2.21.2 — design pass: calm surface, deep underneath (2026-08-19)

- Charts: `ui.regime_bands` now draws a faint 10 % tint + a saturated baseline ribbon (Pairs and
  Storms share it via `ui.runs_from_labels`); Plotly axes muted mono 11 px; Pairs x-range ends at
  the as-of date (no dead gap); scheduled-decision markers sit on the ribbon.
- Banner trace: alarm-line hairline at 0.22, end dot, "90 days ago · today" anchors.
- Progressive disclosure: market-card narration clamped to three lines (full text on Pairs);
  treasury reason clamped to two; market tabs (universe + pair, synced with the sidebar) shown in the
  header on every width; nav group labels mono-uppercase; inputs defined (nimbus field + hairline,
  accent focus); table row hover; active tab accent.
- Fix: the live scoreboard is written to `reports/` only for the real ledger — the test suite had
  been overwriting it with fixture numbers (the committed phase-20 copy was polluted; regenerated).
- `tools/screenshot.py` uses a clean Chrome profile (no remembered sidebar state).

## v2.21.1 — technical report (2026-08-19)

- `docs/paper/`: the 53-page technical report (HTML source in four parts + generated PDF, figures regenerated
  from the committed artifacts with the design tokens): abstract, principles, data, the six models with
  their mathematics and frozen numbers, strategy/stress honesty, ledger/drift/proof, calendar &
  challenger, central-bank index and the refusal note, treasury mode, storm replays, pipeline/wall/Rust,
  trust-first UI, go-to-market, limitations, an interview companion, glossary and repo tour.
- `narrate.py`: replies are now rejected (→ template) if they contain direction words (rule-5 guard), tested.

## v2.21.0 — phase 31: trust-first UI (2026-08-19)

- Tokens: `design/tokens.json` is the single source (nimbus #0E1420 / front #151D2E / hairline
  rgba(255,255,255,.08); text #E8ECF4 / #9AA6B8 / dim #7B89A1 — the mockup's #5C6980 lifted for
  4.5:1; regime calm #3ECF8E · trend #4DA3FF · chop #F5B942 · crisis #FF5C5C; beacon #7FD1C9; light
  e-mail variant). `fxradar.tokens` loads it; `scripts/gen_tokens.py` (`make tokens`) regenerates
  `.streamlit/config.toml`, `design/tokens.css` and the Rust static tokens; `app/ui.py`, the Plotly
  template (transparent, 6 %-white grid, `ui.regime_bands`), every matplotlib report figure
  (forecaster / siren / strategies / stress / validate / features_ext / event studies / replay), the
  orb presets, viz3d, the weekly e-mail HTML and `widget.js` now read from it. `make lint-ui` (CI)
  fails on any hex literal in app/, src/, scripts/, pipelines/; `tests/test_design_tokens.py` checks
  no-hex, AA contrast on both surfaces, config/widget/orb agreement, fonts ≤ 500, motion budget.
  CLAUDE.md design section rewritten to match.
- Type: Space Grotesk (display: regime words, titles), IBM Plex Sans (UI), IBM Plex Mono with
  'tnum' for every number/hash; tables right-align numbers; no weight above 500 anywhere.
- Signature structures in `ui.py`: `condition_banner` (eyebrow pair + data-through, the regime
  word huge in its colour, change risk ± band · siren, `risk_trace_svg` 90-day trace with shaded
  band, three-dot consensus) and `trust_strip` (forward-test days, live Brier vs frozen, coverage vs
  90, chain head ✓, "verify independently") + `live_dot` (the only motion besides the orb; off under
  reduced motion) + `state()` for directive empty/error copy.
- IA: Radar = Overview (banner, next scheduled storm, treasury light, interval coverage, alerts,
  compact market cards) · **Pairs** (new page: the full card, close with regime bands + the orb,
  scheduled-decision markers, anatomy, siren) · Treasury · Storms · Proof; Analysis = Advisor ·
  Regime space · Probability space · Strategy lab · Arcade; About = Methodology · Weekly report ·
  Metrics. Responsive to 360 px (banner clamps, single-column tiles); visible focus rings.
- Public surfaces on the same tokens: Proof, weekly HTML, widget.js, README hero
  (`docs/screenshots/overview_v3.png`), og-image, orb four-state strip with the new colours.

## v2.20.0 — phases 29 + 30: central-bank communication index (Stage 1) + the gated Stage 2 (2026-08-19)

- phase-29a `cb_text`: official FOMC / ECB / SNB / BoE statement fetcher (stdlib HTML parser, polite,
  dedup by bank+date, idempotent, fixed publication times: ECB 14:15 CET · SNB 09:30 CET · BoE 12:00
  London · FOMC 14:00 ET) — 184 statements 2020→2026-07 in `data/cb/` (PDF-only months: SNB via
  optional pypdf; three BoE MPR months missing, noted).
- phase-29b `cb_lexicon` + `cb_features`: frozen, sha256-pinned lexicon (`data/lexicon/`: official
  Loughran-McDonald uncertainty list + a cited hawkish/dovish list, LICENSE_NOTE) → per-document hawk /
  dove / tone / uncertainty; daily point-in-time features `cb_<bank>_tone / _uncert / _tone_surprise
  (vs the bank's last 4) / _days_since` known from the publication timestamp (17:00 New York day
  boundary) → `data/cb_features.parquet`, merged into features_ext for the CHALLENGER only;
  truncation invariance bit-for-bit.
- phase-29c `cb_finbert`: pinned `ProsusAI/finbert@4556d130…`, lazy import, `LiveOnlyError` raised
  BEFORE any import for any document dated before the 2026-08-17 deploy; `requirements-nlp.txt`
  (torch/transformers) never in requirements.txt or CI.
- phase-29d `scripts/cb_event_study.py`: |tone surprise| vs 5-day vol and 10-day regime flips with
  placebo + permutation bands → `reports/cb_index.md`: a calendar effect exists (days after any
  statement are more volatile), no credible surprise effect yet; live tracking table on the Proof
  page; README parametric-look-ahead paragraph.
- phase-30 (GATED — CLOSED): live counts 0/16 FOMC, 0/16 ECB, 0/8 SNB, 0/16 BoE →
  `docs/stage2-decision.md` (the documented no). Inert `cb_llm` shipped: versioned
  `prompts/cb_hawkishness_v1.txt`, receipts (prompt sha256 + version, model, date, raw reply),
  cost cap 60/yr, ops-log skip, the same pre-deploy guard (tested), no bypass flag; **no API call was
  made**. `docs/why-we-refuse-the-backtest.md` — the one-page refusal note, linked from the README top.
  28 tests.

## v2.19.0 — phase 23: calendar + cross-asset + mood + Yang-Zhang, challenger-only (2026-08-19)

- `data/events.csv` (1 227 scheduled decisions 2005→2026-12 from the official FOMC / ECB / SNB / BoE /
  BLS calendars; unscheduled actions excluded — 2015-01-15 is deliberately unknown); `calendar_ext`
  (`days_to_*` / `days_since_*`, calendar days), `context_data` (FRED: broad-dollar index as DXY
  proxy, VIX, US 2y, daily EPU; EURCHF via yfinance as context; CFTC TFF leveraged-money EUR with the
  explicit Friday release lag — tested), `features_ext` (lags per series, z-scores with train-only
  params in `models/features_ext_scaler.json`, `yang_zhang()` → `vol_20_yz`; cache-first, offline
  fallback) → `data/features_ext.parquet` (49 cols incl. the phase-29 tone features); truncation
  invariance for EVERY column.
- `challenger`: same recipe as the champion on the extended matrix, `models/forecaster_challenger_v1.0.0`;
  frozen test (scored once): PR-AUC 0.544 / Brier 0.103 vs champion 0.548 / 0.102 — no lift; both now
  write to the ledger under distinct segments; promotion = live PR-AUC ahead over ≥ 60 matured days
  with Brier not worse, by a deliberate refit-path act (`reports/challenger_eval.md`).
- `scripts/event_study.py`: −10..+10 windows per type with ≥ 1 000 placebo draws → `reports/event_study*.png`;
  SNB day-0 regime-flip frequency 6.7 % vs placebo 3.5 %; change-risk curves mostly inside the band.
  Event markers on the Pairs timeline (`data/event_markers.json`). `reports/yz_ablation.md`: refitting
  the HMM on vol_20_yz relabels 33–69 % of days → adopting YZ is a full bundle rebuild (follow-up).
- The wall: `data/features.parquet` columns, `feature_spec`, bundle, goldens and Rust byte-identical;
  selftest PASS.

## v2.18.0 — phase 28: first revenue rails (2026-08-19)

- Tiers written down: Free (weekly report + public widget) · Pro CHF 79/month (alerts on chosen
  pairs, Treasury mode, monthly PDF) · Partner CHF 500+/month (API + white-label); monthly, cancel
  any time, no annual-only lock-in — `docs/PRICING.md`. Enforcement lives in the phase-24 middleware;
  the Stripe test-mode webhook (phase 24 commit) moves a key between tiers; TEST MODE until the first
  design partner converts.
- `docs/TERMS.md` + `docs/PRIVACY.md` (plain-language DRAFTS, rule-7 disclaimer, TODO: confirm
  Swiss FinSA specifics with a professional before going live); footer links on every page.
- Outreach kit `docs/outreach/`: design-partner e-mail in German and English (≤ 150 words; six months
  free for a monthly feedback call + signed LOI at CHF 79/month if useful), one-page LOI template,
  target criteria (Swiss SMEs with EUR/USD invoicing, fiduciaries, treasury associations),
  `tracking.csv` (15 placeholder rows, no personal data). Metrics page shows design partners + MRR
  from the tracking file — honest zeros. Nothing is sent, nothing is charged: ten conversations come
  before the next feature.

## v2.17.0 — phase 24: productised API (rust/fxradar-serve v2.11.0) (2026-08-19)

- `X-API-Key` auth: sha256-only sqlite store (`--keys-db` / `FXRADAR_KEYS_DB`, default
  `data/keys.db`, gitignored), `keys` admin CLI (issue — plaintext printed once — list / revoke /
  set-tier / webhooks), tower middleware 401 unknown · 403 tier · 429 + Retry-After per-key token
  bucket (60/min default). Tiers free | pro | partner: public routes stay open (health, regimes,
  /docs, /metrics, /widget.js, /widget, stripe webhook); POST /api/score, GET /api/treasury and
  /api/webhooks need pro or partner.
- Alert engine: tokio poll loop over the newest artifact rows (300 s default, once at startup);
  triggers regime flip · anomaly_pct > 98 · consensus 3/3; persisted `last_alerted` state per
  (key, pair, trigger) → one flip = one alert; mpsc delivery queue, ≤ 5 tries with exponential
  backoff, never inside handlers; payload signed HMAC-SHA256 over `ts.body`
  (`X-FXRadar-Signature`, `X-FXRadar-Timestamp`); generic / Slack / Telegram adapters; template text =
  regime, change risk ± band, consensus line, next scheduled event; direction-word lint test.
- OpenAPI via utoipa + Swagger UI at `/docs`; Prometheus `/metrics` (requests, latency histogram,
  alerts fired, delivery outcomes); `/widget.js` badge (regime dot + word + siren, tokens palette,
  `?partner=` attribution) + `/widget` demo; `/api/regimes` now mtime-cached (9.6k req/s vs 43).
  `docs/API.md`, `tools/verify_webhook_sig.py`, `tools/load_test.py`, BENCH.md phase-24 numbers
  (/api/score ≈ 2 180 req/s at c = 8, p50 3.6 ms, p99 4.4 ms), `docs/DEPLOY_ORACLE.md` §7 (systemd +
  env-file, ports, health check, first key). Startup gate + golden selftest byte-identical.
- phase-25 (rust): `GET /api/treasury` reads `data/treasury_risk.json`; optional
  `?pair&amount&weeks&level` → ES notional = amount × es × √weeks (arithmetic only, 404 if absent,
  disclaimer in JSON).
- phase-28 (rust): `POST /api/stripe/webhook` verifies `Stripe-Signature` (HMAC over `t.payload`,
  5-minute tolerance, `STRIPE_WEBHOOK_SECRET` from env) and maps checkout / subscription events to key
  tiers (cancel → free); TEST MODE, no SDK. docker-compose: keys volume + env.

## v2.16.0 — phase 26: storm replays + auto post-mortems (2026-08-19)

- `fxradar.replay`: replay engine on the REAL scoring path — prices truncated at each day t, the
  same loaded HMM/forecaster/siren bundles run_daily uses, BOCPD + consensus + conformal band when
  present; bit-identical to `regimes.parquet` and to the live ledger rows (tested, diff 0.0). Three
  windows fixed in advance: COVID 2020 (EURUSD), Credit Suisse 2023 (USDCHF), SNB floor removal 2015
  (USDCHF) → `data/storm_replays.json`, `reports/storms/*.md` + png. Honest numbers: COVID first alarm
  2020-02-28, crisis label 2020-03-20; Credit Suisse — first alarm 2023-03-13, no crisis label in the
  window; SNB — change risk 14–23 % in the five days before, siren 100 on 2015-01-15 while the label
  still read calm, crisis on the 16th: the radar did **not** warn, and the sidebar says why a vol-based
  radar is blind to a pegged cross. Every page/report carries "causal reconstruction — not the live
  record" + the selection rule. `replay.stage`: on a live entry into crisis, drafts
  `reports/postmortems/<date>_<pair>.md` flagged for human review. Storms page; `docs/STORMS.md`;
  12 tests (replay == artifact, replay == ledger, truncation, windows fixed, "no warning" reported).

## v2.15.0 — phase 27: weekly FX weather report + public metrics page (2026-08-19)

- `fxradar.weekly`: deterministic Monday report per pair (regime, change risk ± band, anomaly
  percentile, generic hedge/wait/ladder light from the treasury artifact — never personalised, days
  to the next SNB/ECB/FOMC/BoE event, `template_narrate` paragraph, proof link, live-record line) →
  `docs/weekly/<date>.md` + e-mail-safe light-mode HTML twin (inline styles, phase-31 light tokens,
  360 px checked) + `docs/feed.xml` (RSS 2.0, last 52) + `docs/weekly/index.md`; `data/ops_log.jsonl`
  records "weekly_report_published" so a silent Monday is visible; direction-language lint over every
  string literal; `.github/workflows/weekly.yml` (Mondays 06:30 UTC, commits the report, feed and
  metrics). `docs/EMAIL_HOOK.md` documents the provider hook; zero paid services.
- `fxradar.metrics_page` → `data/metrics.json` + README table: ledger days live, forecasts
  recorded/resolved, report subscribers, active API keys (from `data/keys.db` when it exists), design
  partners and MRR (from `docs/outreach/tracking.csv`), weekly reports published — honest zeros.
  App pages **Weekly report** and **Metrics**. 16 tests.

## v2.14.0 — phase 25: treasury mode (2026-08-19)

- `fxradar.treasury`: regime-conditional 1-week VaR/ES (historical simulation of |5-day log move|,
  labelled by the filtered regime at the window start, train era only; cells with < 30 windows fall
  back to the unconditional table with a flag) + deterministic hedge / wait / ladder rule table with
  train-era thresholds (HIGH 0.305 / LOW 0.090 change risk; band width 0.25 / 0.12 defaults until the
  conformal q is wired); pipeline stage writes `data/treasury_risk.json` (table × regime × level,
  current regime pointer, light + reason, latest crosses for conversion).
- Treasury page: exposure → light + VaR/ES in the home currency (√t scaling beyond one week, stated
  as an approximation), the cost-of-waiting line ("Waiting 1 more week on €800,000 risks ≈ CHF 20,000
  at the 99 % level"), per-regime conditioning table; arithmetic on the artifact only. `docs/TREASURY.md`
  (method, limits, compliance posture, FinSA TODO); direction-word lint over every template; 12 tests.
  Honest finding: USDCHF's *calm* ES99 (7.6 %) exceeds its crisis cell because the 2015-01-15 SNB
  windows start in calm — the shock arrived unannounced.

## v2.13.0 — phase 22: Mondrian conformal intervals + coverage receipt (2026-08-19)

- `conformal.py` (~30 lines of math): calibration rows = 2017–2018 validation only
  (asserted), per-regime finite-sample quantile of |y − p̂| (α = 0.1; regimes with < 30 rows borrow
  the pooled q), `[p̂ ± q_r]` clipped; `models/conformal_v1.json`; frozen-test coverage receipt 91.6 %
  (per regime 90–93 %) + 120-day rolling series and live coverage on matured ledger rows →
  `data/conformal_coverage.json`; gauge band on the cards ("bands are wide on purpose" in crisis);
  README exchangeability paragraph; pipeline stage `conformal`; ledger columns `risk_lo/risk_hi/conformal_q`.
  Tests: coverage within 90 ± 3 pp, crisis q > calm q, calibration dates inside 2017–2018,
  deterministic, committed params reproduce.

## v2.12.0 — phase 21: BOCPD + three-voter consensus (2026-08-19)

- `bocpd.py` (~100 lines numpy): Normal-Inverse-Gamma BOCPD, hazard 1/60, pruning 1e-6,
  MAP run length + P(change ≤ 5d); train-era prior scale and voter thresholds in
  `models/bocpd_params.json`; consensus = HMM crisis prob ≥ train p95 (clipped 0.2–0.5) + BOCPD
  ≥ train p90 + `validate.naive_stress` verbatim → `agreement` 0–3 + template sentence; pipeline
  stage `bocpd`; consensus meter on the weather cards; ledger columns. Tests: bit-for-bit truncation
  invariance, planted vol/mean breaks flagged within days, determinism, no direction words.

## v2.11.0 — phase 20: live ledger v2 + drift monitor + public proof (2026-08-19)

- `ledger.py` schema 2: rows carry the four filtered probabilities (`hmm_model.score_pair`
  now emits `p_calm…p_crisis`; `REGIME_COLUMNS` extended), conformal band, BOCPD outputs, three votes
  + agreement, git SHA, `schema`, `correction_of`; hash = sha256(prev_hash | canonical sorted-key
  JSON) over the schema's field set — legacy schema-1 rows keep their original hash and are never
  rewritten; `append_correction` (new row pointing at the original); champion/challenger families keep
  separate newest-date pointers; `scoreboard()` per model-version segment → `reports/live_scoreboard.md/.json`;
  `data/ledger_head.txt` + canonical `data/ledger.jsonl` mirror; `scripts/verify_ledger.py` (stdlib,
  36 lines, VALID/BROKEN + head). `drift.py`: PSI (10 train quantile bins; status judged against the
  train-era distribution of 60-day-window PSIs because regime-switching features sit at PSI 3–8 inside
  train), KS, HMM staleness (predictive log-likelihood vs train p5) → `data/status.json` with
  `model_stale`; header badge. New app page **Proof** (trust strip, scoreboard, coverage receipt, drift
  tables, verify box, ledger download). README live sentence "Since <deploy>: live PR-AUC / Brier vs
  frozen". Tests: tamper/delete → BROKEN, double run → one row per pair, unmatured rows refused,
  legacy file verifies from genesis, drift fires on shifted fixtures. Pipeline stage `drift`
  registered after the siren, before the ledger; CI runs the public verifier.

## v2.10.1 — always-on deploy: Docker + Oracle Always-Free (2026-08-18)

- Cloud Run path: image honours `$PORT`; `deploy/cloudbuild.yaml` (Cloud Build, no local Docker);
  `.github/workflows/cloudrun.yml` (build → Artifact Registry → `gcloud run deploy`, session affinity,
  1 h timeout, min-instances configurable; inactive until `GCP_PROJECT` is set; also runs after each
  successful `daily-refresh`); guide `docs/DEPLOY_CLOUD_RUN.md` with cost notes.

- `deploy/`: self-contained app image (`Dockerfile`, python:3.11-slim, non-root, healthcheck; every
  dependency has aarch64 wheels so it builds on Ampere A1), `docker-compose.yml` (app + Caddy with
  automatic HTTPS via `SITE_ADDRESS`, restart policies, artifacts bind-mounted from the git checkout),
  `Caddyfile`, `refresh.sh` (nightly `git pull` → restart on artifact-only changes, rebuild on code
  changes), `cloud-init.yaml` (Docker install, iptables 80/443, clone, first build, cron),
  `.env.example`; `.dockerignore`; `make docker` / `make docker-down`; CI workflow `docker image`
  (build + health check); guide `docs/DEPLOY_ORACLE.md`; README Deploy section updated.

## v2.10.0 — phase 19 (plan “24”): signature 3-D visuals, display layer only (2026-08-18)

- `src/fxradar/viz3d.py`: `simplex_coords` (exact `probs @ V`, order asserted, rows validated,
  uniform → origin), `filtered_probability_table`/`probability_frame` (replay of the frozen bundle's
  causal forward filter — never the smoother; the replay reproduces regimes.parquet exactly),
  `tetrahedron_figure` (6 edges, 4 labelled vertices in the regime palette, path coloured by time or
  siren, ringed today, hover with the four probabilities, all axes/planes hidden, `aspectmode="data"`),
  `fit_landscape_embedding` (scaler + PCA(3, random_state=42) FIT ON TRAIN ROWS ONLY, `train_end` and
  `n_fit_rows` stored; umap only if importable), `save/load_embedding` (joblib dict next to the models),
  `landscape_figure` (days by regime, 60-day brightening trail, ringed today), offline CLI `--fit`.
  Adaptation: the HMM consumes only 3 features (PCA(3) would be a rotation), so the landscape embeds
  the 8 causal base features with a train-only scaler.
- App: new page Radar → *Probability space* (`app/views/probability_space.py`): pair + colour-by
  segmented controls, explainer copy per figure, (A) above (B), universe-aware; every other panel
  unchanged and 2-D. Embeddings fit and committed for both universes (`models/landscape_*_pca.joblib`).
- `scripts/make_gif.py` + `make gif`: 72 frames × 5°, fixed elevation, 600 px, kaleido → imageio →
  `assets/tetrahedron.gif` (1.5 MB), embedded at the top of the README with the one-line caption;
  `make viz3d` fits the embeddings; `requirements-dev.txt` (kaleido, imageio — dev only).
- Tests `tests/test_viz3d.py` (13): exactness, validation, order guard, leakage (train-only fit,
  future-perturbation invariance), determinism + round trip, replay-vs-regime-table agreement.

## v2.9.1 — regime space: the feature space in 3-D (2026-08-18)

- New page `app/views/regime_space.py` (Radar → Regime space): the HMM's feature space rendered in WebGL,
  the only 3-D *chart* in the app (the orb is ambient) because the third axis is a real dimension,
  not a decorated time series.
  *State-space portrait*: one point per day at (realised vol log, 1-month momentum, selectable third
  axis), coloured by the day's filtered regime; regime centres; a 20–120-day trail to the ringed as-of
  marker; other pairs' same-day ghosts; ▶ replays the last year (~125 Plotly frames, every 2nd day,
  hover text computed once — the frame build is the page's cost, ≈ 0.45 s warm). *Regime landscape*:
  numpy 2-D histogram + binomial blur → density terrain over (vol, momentum), surface colour = dominant
  regime per cell in vol order (calm→crisis) so adjacent regimes get adjacent colour bands; empty cells
  are cut out (NaN) and inherit the nearest populated cell's colour index (else Plotly's per-face colour
  interpolation paints rainbow rims). *Geometry readout*: vol percentile, momentum, z-scored distance to
  each regime centre — labelled as a reading aid, distinct from the HMM probability.
- Reads `features.parquet` + `regimes.parquet` only, filtered to the as-of date (scenario explorer and
  deep links `?pair=&asof=` work); both universes; no new dependency (Plotly; scipy `distance_transform_edt`
  is already installed with scikit-learn).
- Router: `Regime space` under Radar; README section + repo tour; screenshots
  `docs/screenshots/regime_space{,_snb}.png`; AppTest `test_regime_space_page_renders_and_replays`.

## v2.8.1 — responsive pass: desktop, tablet, phone (2026-08-18)

- Regime orb fits its column: responsive square wrapper, canvas sized to the space it gets
  (`ResizeObserver`), `st.iframe(width="stretch")`; the orb column widened to `[1, 5]` and
  vertically centred with the chart title (it used to be clipped to a slice in a 1/8 column).
- One layout that adapts (no device sniffing): `@media` rules in `app/ui.py` — stacked header, 2×2
  KPI grid, tighter cards, scrollable tables (`.fx-table-wrap`), ≥ 40 px touch targets, orb hidden
  ≤ 640 px, three-across blocks two-across on tablets ≤ 1024 px, responsive sparklines.
- Mobile control bar (`ui.mobile_bar`): universe + market as `st.segmented_control`, hidden on
  desktop by CSS; kept equal to the sidebar selectboxes by `on_change` callbacks (widget values now
  live in session state — no `index=`, no Streamlit "default + session state" warning).
  `initial_sidebar_state="auto"` (collapsed on phones); the header stays (transparent, click-through)
  so the » open-sidebar button is reachable — it was hidden together with the toolbar before, which
  also stranded desktop users who collapsed the sidebar. Sidebar icon font no longer overridden
  (collapse arrow rendered as the ligature text `keyboard_double_arrow_left`).
- `tools/screenshot.py`: `--width/--height/--mobile/--eval` (device emulation, software WebGL, DOM
  introspection); AppTest `test_mobile_bar_mirrors_sidebar_controls_both_ways`.

## v2.9.0 — live forward-test ledger + real badges (2026-08-18)

- `src/fxradar/ledger.py`: append-only, SHA-256 hash-chained record of every forecast the pipeline
  publishes — one row per pair for the NEWEST date only (never backfilled: a forecast counts only
  if it was written down while its day was the latest observation, i.e. before the outcome could
  be known). Rows carry regime, change_risk_5d, anomaly_pct, model_version, recorded_at_utc,
  prev_hash → row_hash (chain over the forecast fields only). Five trading days later rows are
  *resolved* with `forecaster.build_labels`' definition verbatim and scored with `forecaster.metrics`
  (PR-AUC, precision/recall at the frozen threshold 0.22, Brier, plus base-rate Brier — never
  accuracy). Metrics are null until 20 rows have resolved and PR-AUC is null with one class
  (degenerate → null, never 0). A model refit starts a new segment; the headline scores the current
  segment only. `record()` refuses to append to a broken chain. Outputs: `data/ledger.parquet`,
  `data/live_record.json`, `data/badges/live_record.json` (shields.io endpoint schema), and the
  README block between `<!-- live-record:start/end -->` markers (fx universe only). CLI
  `python -m fxradar.ledger --record` / `make ledger`; both universes seeded (2026-08-17 close).
- Pipeline: new `ledger` stage after siren, before narrator; files written in the write stage
  (all-or-nothing preserved). `stage_forecaster` keeps `forecaster_meta` in ctx.
- README: **Track record — frozen test vs live forward record** headline table right under the intro
  (frozen 2019+ column beside the live column, warming up until 20 resolved, chain status, updated
  date). Badges are now REAL: `ci` (new `.github/workflows/ci.yml`: ruff + black + pytest + ledger
  chain verification, on every push/PR; data commits carry [skip ci]), `daily refresh`, `rust engine`
  workflow badges, and a dynamic `live record` shields endpoint fed by the pipeline. `OWNER/REPO`
  placeholder: `make set-repo REPO=you/name`, and the daily job substitutes `github.repository` on
  its first run. `daily.yml` now commits `README.md` alongside `data/`.
- App: Overview KPI tile "live record" (Brier since deploy vs base rate once warm, else warm-up
  progress); Methodology card "The live record — what the deployed models actually said".
- Tests (`tests/test_ledger.py`, 12 + 2 pipeline): newest-date-only + idempotent + forward-only
  append, tamper/delete/relabel breaks the chain, resolution == `forecaster.build_labels` exactly
  (day-by-day replay), idempotent resolve, summary null while warming up then equal to
  `forecaster.metrics`, current-segment scoring, single-class nulls, README block idempotent and
  local, warming-up renderers, twelve-run round trip through disk, broken chain refused, stage
  order + deferred writes; total 133.

## v2.8.0 — advisor + app shell (2026-08-18)

- `src/fxradar/advisor.py`: Market Stability Index (0–100; weights regime 0.35, change risk 0.20,
  siren 0.20, vol front 0.15, entropy 0.10; words Fair/Unsettled/Stormy/Severe), regime
  durability (1/(1−p) typical run vs current, memoryless note), risk budget (share of the user's
  own normal size: ×(1−risk) above 0.30, crisis ½, chop 0.8, siren >90 ×0.7, >98 → 0) with
  reasons, inverse-vol allocation, sizing calculator (capped 2×), `snapshot()` evidence base per
  universe/as-of, and `answer()` — LLM Q&A grounded ONLY in the snapshot with a guardrail system
  prompt (never direction/buy/sell/outside facts, cites fields) and template answers (direction
  questions are refused). Pipeline stage `advisor` writes `data/advisor.json` per universe.
- App shell: `app/app.py` is now a router (`st.navigation`: Radar → Overview, Advisor; Research →
  Strategy lab, Arcade; About → Methodology), pages moved to `app/views/`; shared sidebar
  (universe · market · scenario explorer) via `ui.scenario_controls`; KPI strip + alerts (crisis,
  siren, high change risk) on Overview; new Advisor view (stability gauges, durability, risk
  budgets with reasons, allocation, calculator, Ask the radar, snapshot expander); CSS polish
  (KPI tiles, section headers, alerts, buttons, expanders, nav). Methodology explains the index,
  durability, budget and the Q&A guardrails; README section.
- Tests: advisor logic (bounds/monotonicity, durability math, budget rules incl. no direction
  words, allocation, sizing, snapshot + template guardrails), router + advisor render, views
  paths; total 118.

## v2.7.0 — universes + scenario explorer (2026-08-18)

- `src/fxradar/universes.py`: one record per instrument set (pairs, tickers, bounds, splits,
  day-count, corrupted-print thresholds, cost model, official cross-check, forecaster pair
  one-hots, siren events, narrator words, artifact sub-directory). `fx` = the shipped defaults
  (bundle/goldens still replay bit-for-bit; Rust selftest PASS); `crypto` = BTC/ETH/LTC, train
  ≤ 2020, val 2021–22, test 2023+, `sqrt(365)`, 30 %/15 %/5 %/60 % print thresholds, 8 bp + 20×vol
  costs. `FXRADAR_UNIVERSE=<name>` selects it; `config.py` derives everything from it;
  `make train-universe UNIVERSE=crypto`; daily workflow refreshes both universes.
- De-hardwired FX-isms: pair dummies, siren events, narrator wording, ECB check, annualisation,
  cost defaults, export "must-include" goldens, chart underlay pair. `corr_20` now averages the
  components that exist on a date (a later-listed pair contributes nothing until it starts) —
  changed identically in Python and Rust; FX outputs unchanged.
- Crypto universe trained and shipped (`data/crypto`, `models/crypto`, `reports/crypto`):
  HMM (BTC calm 31 % vol → crisis 107 %; COVID/May-2021/Terra/FTX all `crisis`), forecaster
  PR-AUC 0.548 (logistic 0.488, base 0.228), siren lights every named crash, strategies +
  stress (S3 regime gate net Sharpe +0.07 test, breakeven 1.15×; the rest negative).
- App: sidebar **universe switch** on every page (pair labels via `Universe.display`),
  **scenario explorer** — named-episode jump list + free "as of" date; the whole page is
  rendered from data ≤ that date (cards, replayed template narration marked "(replay)", chart
  cut at the date with an "as of" marker, siren, loudest days), with a time-machine banner;
  deep links `?universe=&pair=&asof=`; log price axis for crypto. Strategy lab / Arcade /
  Methodology follow the selected universe.
- Tests: universe registry (FX defaults, crypto consistency), scenario explorer + universe
  switch flow, deep-link seeding; total 112.

## v2.6.0 — phase-18: regime orb (2026-08-18)

- `app/orb.py`: self-contained three.js (r128 from cdnjs) particle orb rendered via `st.iframe`
  (successor of `components.v1.html`), one hero orb for the selected pair beside the chart
  title (one WebGL context; the HTML card grid stays static — no layout shift). Four presets
  (calm slow drift / trend directional spin / chop high jitter / crisis fast chaos) in one JS
  object mirroring the Python `PRESETS` dict; regime → colour + motion, jitter × (1 +
  change_risk_5d), decaying pulse when anomaly_pct > 98. A display of the parquet numbers —
  computes nothing.
- Discipline: 900 particles (≤ 1 000), rAF paused on `document.hidden`, `prefers-reduced-motion`
  → gentle drift with zero jitter/chaos, three.js/WebGL failure → the flat regime dot in the same
  box (verified: fallback keeps the 220 px wrap height), hover/tap caption "what am I looking
  at", no sound, no faces, no orb on the reading pages. Snippet ≈ 7 KB; three.js ≈ 150 KB gz
  from CDN. Measured JS + render cost 0.23–0.34 ms per frame under headless software GL ≈ 2 %
  of one core at 60 fps (screens: `docs/screenshots/orb/orb_states.png` — calm, trend, chop,
  crisis, crisis pulse, reduced motion, fallback).
- Methodology page: one line on the mapping. `docs/DEMO_SCRIPT.md`: the orb beat. README: orb
  section + v3 react-three-fiber note. Test: orb render smoke (presets, pulse flag, fallbacks).

## v2.5.0 — phase-17: calibration arcade (2026-08-18)

- `src/fxradar/arcade.py`: sqlite store at `data/arcade.db` (calls, visits, badges, gallery
  opens, events; gitignored — user state, reset on free-tier redeploy, v3 Postgres makes it
  durable); one call per pair per ISO week; ANTI-ANCHORING enforced in Python —
  `pre_lock_payload` carries no model value (asserted), `place_call` stores the model's
  change_risk_5d at lock time and only `post_lock_view` reveals it; `resolve_calls` (pipeline
  stage `arcade`, write phase) resolves matured calls after 5 trading days from regimes.parquet
  and scores user and model with the Brier score on the identical question; season ledger
  (rolling Brier both sides, wins = lower Brier per call); watch streak (consecutive UTC days);
  ranks observer → forecaster → storm chaser → regime master driven ONLY by resolved calls and
  rolling Brier; five badges in one rule table; profanity-filtered nickname, no accounts.
- `data/storms.yaml`: five hand-curated storms (SNB 2015, Brexit 2016, GBP flash crash 2016,
  March 2020, 2022) with date/pair/siren percentile cross-checked against the artifacts and a
  3-line story each, `verified: true` — the developer should re-read them (rule 13).
- `app/pages/3_Arcade.py`: banner "a calibration game: forecasting practice, not trading.",
  nickname, observatory (rank, streak), season ledger, badges, call cards with slider + lock
  flow (model number appears only after the lock), storm gallery unlocked by opening a story,
  storage note. No urgency, no money, no trading language, zero nags without a nickname.
  Methodology page records the "methodology reader" badge event.
- Tests (`tests/test_arcade.py`, 8 + app cycle): Brier hand values; resolution flip on day 3
  vs day 6 vs not matured; lock-before-reveal (payload has no model value; one call/week);
  resolution + ledger; streak rollover at midnight UTC; rank rules; badge rules; nickname
  filter and storm loading. App test plays a full cycle: pre-lock render has no model value,
  post-lock shows it.

## v2.4.0 — phase-16: stress lab (2026-08-18)

- `src/fxradar/stress.py` + `python -m fxradar.stress` → `reports/stress_report.md` (one section
  per test, a verdict sentence each, summary table), `stress_bootstrap_dd.png`,
  `stress_robustness.png`, `data/stress_tests.json` for the app.
- Tests run: (1) historical replays — SNB week Jan 2015, COVID crash Feb–Mar 2020, 2022 —
  return / max DD / worst day per strategy + the siren stop's firing dates (197 pair-days);
  (2) cost shocks at 2×/3×/5× and the BREAKEVEN COST multiplier (S1 0, S2 0.1, S3 0, BLEND 0 —
  no strategy has a positive gross Sharpe on the test set except S2 barely, so there is no edge
  to pay costs from); (3) execution shock, one extra day of lag (Sharpe change −0.00…+0.19);
  (4) volatility shock, crisis returns ×1.5 (worst DD deepens 0.5 % only — the overlay takes risk
  off in crisis); (5) 20-day block bootstrap, 1 000 one-year paths (BLEND median max DD −6.2 %,
  5th-pct pain −10.2 %); (6) ±30 % parameter robustness heatmaps (BLEND net Sharpe band 0.86: a
  flat negative plateau — nothing overfit, nothing good). Nothing was re-tuned.
- Strategy-lab page: compact stress panel (breakeven table, replays, bootstrapped drawdowns +
  histogram). README results section updated with the strategy-layer verdict.
- Tests (`tests/test_stress.py`, 4): moving-block bootstrap preserves autocorrelation
  (vs day-shuffle) and shape; params override restores; breakeven semantics (positive gross →
  positive multiplier, negative gross → 0); window stats.

## v2.3.0 — phase-15: strategies and blend (2026-08-18)

- `src/fxradar/strategies.py`: S1 trend (clip(mom_20/3 %)), S2 mean reversion (−clip(z_5d, ±2)/2
  with z = 5-day return / expected std), S3 regime gate (S1 in trend, S2 in chop, ½·S1 in calm,
  flat in crisis) — mechanical rules, no fitted direction. Insurance overlay on every strategy:
  ×(1 − change_risk_5d) above 0.30, flat when anomaly_pct > 98 (siren stop), vol targeting to
  10 % per pair on the strategy's own trailing 60-day realised vol, leverage capped at 2×
  (engine `max_position`). Blend: monthly inverse-vol weights from trailing 120-day pooled net
  vol, lagged (causal). One PARAMS block, fixed on train+val, comment forbids further tuning;
  test 2019+ scored once.
- `reports/strategy_eval.md` + `strategy_equity.png` (net equity, EURUSD regime underlay,
  validation/test dividers): gross vs net for train/val/test, per-regime net Sharpe
  attribution, correlation matrix, the mutual-insurance verdict (blend max DD does NOT beat the
  best single strategy in the test sample), vol-target/cap note (cap binds 46–81 % of days →
  realised 6–9 %), honest closing paragraph. Test net Sharpe: S1_trend -1.23, S2_meanrev -1.36, S3_regime_gate -1.30, BLEND -2.18. Expected outcome, stated
  in advance: after realistic costs the edge is absent; the framework and the honesty are the
  deliverable.
- Artifacts: `data/backtests.parquet` (S1–S3 + BLEND), `data/strategy_metrics.json`,
  `data/strategy_attribution.json`. Dashboard page `2_Strategy_lab.py`: net equity, drawdowns,
  gross/net metrics with period selector, per-regime attribution, correlation, banner
  "research demonstration on daily data — not a live trading system".
- Tests (`tests/test_strategies.py`, 6): overlay forces flat on siren days and scales by risk;
  strategies in [−1, 1] and causal; regime-gate semantics; vol targeting on train (10 % ± 2 %
  or capped-and-below, never hotter); blend weights monthly/inverse-vol/causal; leverage never
  above cap in the saved backtests. Plus the Strategy-lab app smoke test.

## v2.2.0 — phase-14: backtest engine (2026-08-18)

- `src/fxradar/backtest.py`: `run_backtest(positions, prices, features, cost_cfg)` — daily bars
  only; THE LAG LAW inside the engine (positions shifted one day: a signal formed at close t
  earns t+1); `CostConfig(base_bps=1, vol_mult=80)` → cost_bps_t = base + vol_mult·vol_20_t
  (measured calm ≈ 5 bp, crisis 12–16 bp; crisis/calm 2.4× EURUSD, 3.1× GBPUSD, 8× USDCHF)
  charged on turnover |pos_t − pos_{t−1}|; daily frame + metrics gross AND net per pair and
  pooled (CAGR, ann vol, Sharpe, max drawdown, annual turnover, cost drag, hit rate);
  `metrics_table()`; `data/backtests.parquet` (date, strategy, pair, pos, ret_gross, ret_net,
  cost_bps) with the always-long demo strategy.
- Demo (always long, all pairs, 2005-03 → 2026-08): net CAGR −0.9 %, Sharpe −0.19, max DD −30 %.
- Tests (`tests/test_backtest.py`, 6): constant long = asset return − exactly one entry cost;
  daily sign flip cost bleed to the cent; THE FORESIGHT TEST (same-day-close signal: Sharpe > 10
  with the lag disabled, |Sharpe| < 1 with it enforced); cost monotonicity in vol_mult; clipping
  + gross/net contract; cost scaling. Note: the spec's `sign(ret_{t+1})` is written as
  `sign(ret_t)` in engine indexing — the sin being tested is contemporaneous lookahead.

## v2.1.0 — phase-13: axum service (2026-08-18)

- `rust/fxradar-serve` binary `fxradar-serve` (axum 0.8 + tokio + tracing): startup gate in
  order — load bundle → verify SHA-256 → run the full golden self-test in-process → only then bind.
  Failure logs the diff table via `tracing` and exits 1; `--skip-selftest` exists and logs a loud
  warning. Demonstrated: a tampered `goldens.parquet` is refused (hash mismatch); a corrupted
  golden with a matching hash is refused by the self-test (`change_risk_5d 5.0e-2 > 1e-6 ✗`,
  "REFUSING TO START").
- Endpoints: `GET /api/health` (bundle version, git commit, selftest status/timestamp/worst
  diffs, uptime, in-memory p50/p99 of scoring latency), `GET /api/regimes/{pair}` (latest row from
  `data/regimes.parquet` via a read-only state store, + `served_by`), `POST /api/score` (raw
  windows for all pairs → full Rust path → ScoredRow JSON). JSON errors with proper status codes
  (400 bad window / unknown pair, 404, 503, 500); request logging with latency (tower-http trace).
- Load check (`tools/load_check.py`, 1 000 real requests): server-side p50 0.42 ms / p99 0.48 ms,
  round trip p50 0.99 ms / p99 1.46 ms; recorded in `rust/BENCH.md`. Live proof: `/api/score` on
  today's USDCHF window reproduces the pipeline's numbers (risk 0.013451, anomaly pct 24.9).
- `rust/fxradar-serve/Dockerfile` (multi-stage rust → debian-slim) and `docker-compose.yml`
  (service :8080 with bundle + data mounted read-only, dashboard :8501 with `FXRADAR_API_URL`).
  Docker was not available on the build machine; the service was verified natively.
- Dashboard: `FXRADAR_API_URL` switch — weather cards take their latest state from
  `GET /api/regimes/*` with a "served by rust v2.1.0" badge next to the timestamp; default
  behaviour unchanged (parquet).
- README "Production serving" section with the wall diagram, the startup-gate story and the
  measured latencies. Rust integration tests: bundle replay + tampered manifest refused; rustfmt
  + clippy clean.

## v2.0.0 — phase-12: rust inference engine (2026-08-18)

- `rust/fxradar-serve/` (cargo crate, edition 2021): `bundle.rs` (manifest SHA-256 verification
  FIRST, serde structs for hmm json / sidecars / feature spec), `features.rs` (exact
  feature-spec semantics from raw price windows incl. pairwise as-of `corr_20`; warm-up 60 rows),
  `hmm.rs` (Gaussian log-likelihood with precomputed precisions/log-dets, forward filter with
  log-sum-exp, entropy, run lengths), `infer.rs` (`Engine`: forecaster.onnx + siren.onnx via
  `ort` 2.0.0-rc.13, Platt calibration, rank percentile → `ScoredRow`), `selftest.rs` + the
  `selftest` binary (parquet goldens → end-to-end replay → per-output max-abs-diff table, exit 2
  on divergence). `thiserror` error enum; no `unwrap`/`expect` in library code; no network, no
  file writes; no Python.
- Self-test on bundle v1.4.0 (302 goldens): PASS — features ≤ 1.1e-13, filtered probs ≤ 1.9e-13,
  regime labels exact, change_risk_5d 3.8e-7, anomaly_score 8e-13, anomaly_pct within one rank.
- Rust tests: constant series, hand-computed vol_20/mom_20/ret_1d, truncation invariance,
  logsumexp stability. `cargo clippy --all-targets -D warnings` clean, `cargo fmt` clean.
- `criterion` benchmark → `rust/BENCH.md`: 0.43 ms per full single-row path, ≈ 2 260 rows/s.
- CI: `.github/workflows/rust.yml` (fmt, clippy, tests, selftest against the committed bundle).
- Bundle rebuilt (manifest git commit/timestamp); export doc note that `probabilities` is a plain
  [n, 2] tensor.

## v1.4.0 — phase-11: model bundle export (2026-08-18)

- `src/fxradar/export.py` + `python -m fxradar.export` → `models/bundle_v1.4.0/`, the ONLY
  artifact that crosses the wall (json/onnx/yaml/parquet — no pickle): `hmm_{pair}.json`
  (means, covariances, precomputed Cholesky-derived precisions + log-dets, transmat, startprob,
  scaler, frozen state names), `forecaster.onnx` (+ sidecar with feature order, Platt a/b,
  threshold), `siren.onnx` (float64, output reshaped to (n, 9); sidecar with scaler + sorted
  calm-train scores), `feature_spec.yaml`, `goldens.parquet` (302 rows across pairs × years ×
  regimes incl. USDCHF 2015-01-15/16; raw 600-day price windows for all three pairs + Python's
  exact features/probs/outputs), `manifest.json` (semver, git commit, model versions, parity,
  tolerances, SHA-256 of every file).
- ONNX parity recorded in the manifest: forecaster max |Δp| 2.7e-7 (16 660 rows), siren 7.1e-15.
- `export.replay_goldens`: the executable contract — from raw windows + bundle files only,
  reproduce every golden (features ≤ 1e-13, probs ≤ 2e-13, change_risk 3.8e-7, anomaly_score
  9e-13; anomaly_pct within one rank step, a documented rank-statistic tolerance).
- `docs/bundle_format.md`; export added as the last step of `make refit` and `refit.yml`.
- Tests (`tests/test_export.py`, 5): manifest hashes verify, tampering detected, HMM json
  matches the saved model (precision × cov = I, log-det), ONNX parity on fresh rows, golden
  round trip. Dependencies: onnx, onnxmltools, skl2onnx, onnxruntime, pyyaml.

## v1.3.1 — phase-10: polish (2026-08-18)

- README rewritten: hero screenshot, pitch, live-link placeholder, mermaid architecture, "How it
  works", Results with the frozen test-set scoreboard + calibration plot, Limitations promoted,
  repo tour, run locally, deploy, disclaimer, badges.
- `docs/model_cards.md` (HMM, forecaster, siren, narrator), `docs/INTERVIEW_NOTES.md` (nine
  answers in the developer's voice, each with a hard follow-up), `docs/DEMO_SCRIPT.md`
  (90-second walkthrough), fresh `docs/screenshots/dashboard.png`.
- Code pass: ruff + black clean, return-type hints on all public functions, build-kit files
  (`START_HERE.md`, `USAGE.md`) moved to `docs/`, no stray files. 77 tests green.

## v1.3.0 — phase-09: narrator (2026-08-18)

- `src/fxradar/narrate.py`: `build_stats(pair)` (numbers only: regime, regime_prob,
  days_in_regime, change_risk_5d, top_drivers, anomaly_pct, nearest-neighbour date, 5-day
  return); `narrate(stats)` via the Anthropic SDK — model `claude-haiku-4-5`, temperature 0.3,
  max_tokens 350, the verbatim guardrail system prompt, user content = the stats JSON only;
  key from env or Streamlit secrets; SDK retries (2, backoff); `template_narrate` writes the
  same three sentences deterministically; `narrate_with_fallback` never raises. Output
  `data/report.json` = {pair: {text, generated_at, source: "llm"|"template", stats}}.
- Pipeline stage `narrator` registered LAST; without a key the pipeline succeeds on the
  template path (verified). `daily.yml` passes the optional `ANTHROPIC_API_KEY` repository
  secret as an env var (empty → template).
- Dashboard: quote-style narration on every weather card with an AI/auto badge and timestamp;
  the app never calls the API (reads `report.json` only).
- README: how to add the key (GitHub secret, Streamlit secrets), cost estimate ≈ 5 ¢/month.
- Tests (`tests/test_narrate.py`, 5): template = exactly three sentences containing the regime
  and the risk figure (+ neighbour only when anomaly_pct > 90); missing key never raises; API
  failure falls back; mocked client receives the system prompt, model/temperature/max_tokens,
  and ONLY JSON-derived user content; build_stats types.

## v1.2.0 — phase-08: anomaly siren (2026-08-18)

- `src/fxradar/siren.py`: `MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=3000,
  early_stopping=True, random_state=42)` autoencoder on the 9 continuous features, scaler +
  model fit ONLY on train-period calm days with regime_prob > 0.7 (2 788 days, 2005-04-07 →
  2016-12-30), pooled across pairs, no pair one-hots (pair-agnostic by design — documented).
- Scoring: `anomaly_score` = mean squared reconstruction error; `anomaly_pct` = percentile
  against the calm-train distribution; per-feature squared errors + nearest historical
  neighbour (same pair, train period, ±10 days excluded) in `data/siren_detail.parquet`
  (for the phase-09 explainer). Scoring is truncation-invariant (tested).
- `reports/siren_validation.md` + `siren_anomaly_pct.png`: SNB 2015-01-15 is USDCHF's
  loudest day in history (rank 1, pct 100); Brexit 2016-06-24 rank 1 for GBPUSD; the
  2016-10-07 flash crash pct 100 (rank 139); March 2020: 68–82 % of days ≥ 98th pct. Honest
  reading: many merely-volatile days also scream; it detects, it does not predict.
- `models/siren_v1.2.0.joblib` (dict payload); manifest entry; pipeline stage `siren`
  registered — `regimes.parquet` now matches the full contract (model_version
  "hmm=0.4.0|fc=1.1.0|siren=1.2.0").
- Dashboard "Anomaly siren" section: SVG dial per pair (muted <90, amber 90–98, red >98),
  2-year sparkline, "Loudest days in history" table for the selected pair.
- Tests (`tests/test_siren.py`, 6): (8,3,8) architecture, scaler/model fit only on calm train
  days (date range + labels asserted), truncation invariance, percentile + outlier behaviour,
  neighbour exclusion window, saved-model SNB check.

## v1.1.0 — phase-07: forecaster (2026-08-18)

- `src/fxradar/forecaster.py`: pooled XGBoost classifier for "regime changes within the next
  5 trading days". Labels look forward; every feature is causal (matrix truncation-invariance
  test). Features exactly per spec (10 numeric incl. filtered HMM outputs + 3 regime one-hots
  + 2 pair one-hots). Time-ordered splits with a 5-day embargo on both sides of every boundary
  (tested). Fixed hyper-parameters, `scale_pos_weight` from train (4.88), early stopping on
  val (iteration 283). No grid search — deliberate.
- Probabilities are Platt-recalibrated on VALIDATION (a=0.95, b=−1.30): `scale_pos_weight`
  makes raw probabilities over-predict (raw Brier 0.128 vs 0.102 calibrated); both are shown.
  Threshold 0.22 chosen on val for recall ≥ 60 %.
- `reports/forecaster_eval.md` (+ `forecaster_calibration.png`, `forecaster_shap.png`), test
  set scored ONCE and frozen: PR-AUC 0.548 vs logistic 0.431, base rate 0.162, one-feature
  rule 0.143; precision 0.45 / recall 0.59 at the threshold; Brier 0.102 (logistic 0.116).
  Honest interpretation paragraph. Never accuracy.
- SHAP TreeExplainer: beeswarm png; per-day top-3 |SHAP| feature names → `top_drivers`.
- Model persisted as `models/forecaster_v1.1.0.json` (+ `.meta.json` with threshold,
  calibration, features, scoreboard); registered in `models/manifest.json`. Pipeline stage
  `forecaster` registered in `run_daily.py`; `regimes.parquet` now carries `change_risk_5d`
  and `top_drivers` (model_version "hmm=0.4.0|fc=1.1.0").
- Dashboard: "5-day change risk" gauge on every weather card (muted <20 %, amber 20–40 %,
  red >40 %) with the top drivers beneath.
- Tests (`tests/test_forecaster.py`, 8): label semantics, embargo gaps, matrix truncation
  invariance, exact feature list, threshold rule, Platt calibration recovers a known
  distortion, top-driver extraction, saved-model contract.

## v1.0.1 — phase-06: automation (2026-08-18)

- `pipelines/run_daily.py`: single orchestrator — stages `data → features → hmm → write`,
  registered with one line each (`register(name, fn)`) so phases 07–09 plug in. Models are
  LOADED (from `models/manifest.json`), never fitted. All compute runs in memory and every
  artifact is written in the final stage only, so any failure leaves `data/` untouched
  (verified: simulated failure → exit 1, files unchanged). Per-stage timings logged; full run
  ≈ 4 s locally. Idempotent: a rerun produces byte-identical parquet files. Writes
  `data/pipeline_status.json` (last run, data-through date, row counts, model versions, ECB
  check, timings) — the app shows "updated … UTC" from it. `FXRADAR_SIMULATE_FAILURE=<stage>`
  rehearses the failure path.
- `.github/workflows/daily.yml`: cron weekdays 06:00 UTC + `workflow_dispatch`; Python 3.11
  with pip cache; runs the pipeline; commits `data/` as `data: daily refresh [skip ci]`;
  `permissions: contents: write`; no secrets.
- `.github/workflows/refit.yml` (manual, inputs train_end + version) and `make refit
  TRAIN_END=… HMM_VERSION=…`: deliberate expanding-window refit that bumps the model version
  via `models/manifest.json`, regenerates the validation report and re-scores.
  `python -m fxradar.hmm_model` gained `--train-end/--version`.
- README: "Run locally" + "Deploy" (GitHub → Streamlit Community Cloud click-path, secrets
  note for phase 09, refit policy, failure honesty).
- Tests (`tests/test_pipeline.py`): success writes all artifacts + status; failure leaves the
  last good state and exits nonzero; simulated-failure env var; stage order.

## v1.0.0 — phase-05: dashboard v1 (2026-08-18) — first shippable

- `app/ui.py` owns the look: Google Fonts (Inter + JetBrains Mono), Streamlit chrome hidden,
  card class (#131A26 surface, 1px #232D3F border, 12px radius, 20px padding), regime pills
  in the four regime colours, one Plotly dark template (`fxradar_dark`) reused everywhere,
  helpers `regime_pill`, `card`, `confidence_bar`, `sparkline_svg`, `html_table`, `sidebar`,
  `footer`.
- `app/app.py`: header (wordmark, "market weather, updated daily", right-aligned "Data
  through …" from the artifact); hero row with one weather card per pair (pair, big regime
  pill, confidence bar, "day N of this regime", last close, inline-SVG 20-day sparkline);
  main panel with pair selector — Plotly close chart with merged regime bands (shapes), the
  out-of-sample divider at 2017-01-01 with annotation, 1y/3y/max range buttons; out-of-sample
  regime anatomy table (same definitions as the phase-04 report). Reads only
  `data/regimes.parquet` + `data/prices.parquet` (light pandas, no model imports).
- `st.cache_data` loaders keyed by file mtime; measured first paint ≈ 1.2 s cold, 0.1 s warm.
- `app/pages/1_Methodology.py`: pipeline, HMM + mood metaphor, filtered vs smoothed in two
  sentences, out-of-sample note, full Limitations. Disclaimer in sidebar + footer on every page.
- `docs/screenshots/dashboard_v1.png` (headless Chrome via `tools/screenshot.py`, main
  content crop). Sidebar holds only the pair selector and the disclaimer.
- Tests (`tests/test_app.py`): both pages render from artifacts without exceptions, carry the
  disclaimer in sidebar and footer, one Plotly figure, load-time budget.

## v0.5.0 — phase-04: hmm validation (2026-08-18)

- `src/fxradar/validate.py` + CLI `python -m fxradar.validate` → `reports/hmm_validation.md`
  with `regimes_timeline_{pair}.png` (close + regime bands, "out-of-sample →" divider at
  2017-01-01, design-system colours) and `regime_durations.png`.
- Sections: (1) regime anatomy train vs OOS (frequency, mean duration, ann. vol, mean daily
  return, worst drawdown inside each label); (2) 5-seed stability table with an honest
  paragraph (EURUSD mean 71 % < 80 % warning; trend/chop split is the fragile part);
  (3) naive baseline — "stressed" when vol_20 > trailing 250-day 80th percentile — agreement,
  Cohen's kappa and dated lead/lag episodes (the HMM does not systematically lead: 4 leads vs
  14 lags across matched episodes); (4) economic-meaning check — toy MA(50/200) rule's Sharpe
  per regime OOS: the "trend best / chop worst" claim FAILS and is reported as such;
  (5) plots; (6) Limitations (daily data, label noise, descriptive not predictive, frozen
  naming rule + SNB, single train window, Gaussian emissions).
- Tests (`tests/test_validate.py`, 7): max drawdown, Sharpe, run lengths, causal naive rule
  (truncation), episode/lead-lag logic, lagged MA rule (+ causality), table shapes.

## v0.4.0 — phase-03: hmm with filtered probabilities (2026-08-18)

- `src/fxradar/hmm_model.py`: one 4-state `GaussianHMM(covariance_type="full", n_iter=1000,
  random_state=42)` per pair on `[ret_1d, vol_20, mom_20]`, StandardScaler and model fit on
  the TRAIN window only (≤ 2016-12-31, `config.TRAIN_END`).
- `filtered_probs`: forward algorithm (per-frame Gaussian log-likelihoods + transition matrix,
  logsumexp-normalised each step) → P(state_t | obs ≤ t). Smoothed posteriors
  (`predict_proba`) are never used for any output. Tested against brute-force prefix
  recompute (60-row toy, atol 1e-8) and for truncation invariance; a companion test shows
  smoothed posteriors are NOT truncation-invariant.
- Frozen naming rule from train-period per-state stats: lowest mean vol_20 = calm, highest =
  crisis, of the middle two the larger |mean mom_20| = trend, other = chop. Persisted with the
  model. Honest note: for USDCHF the "crisis" state collapsed onto the 20 SNB-shock days
  (2015-01-16 → 2015-02-12; mean vol_20 65 %), so its 2008–11 stress carries the "chop" name
  — reported as-is for the phase-04 honesty report (clipping inputs was tried and made seed
  stability worse, so the spec-exact setup is kept).
- Outputs per pair/day: `regime`, `regime_prob`, `hmm_entropy` (nats, max ln 4),
  `days_in_regime`, `vol_trend` (sign of the 10-day change in vol_20), `model_version`
  ("hmm=0.4.0"). Written to `data/regimes.parquet` (the CLAUDE.md contract name — no
  `_base` variant; phases 07/08 enrich it in place) and the three post-HMM columns appended
  to `data/features.parquet`.
- Models: `models/hmm_{pair}_v0.4.0.joblib` (plain dict payload: model, scaler, mapping,
  train_end, version, features). CLI `python -m fxradar.hmm_model [--refit] [--stability]`
  loads saved models by default (never refits in the daily path).
- Results: mean regime_prob 0.96–0.98; transition-matrix diagonals 0.95–0.985 (sticky).
  5-seed label agreement vs seed 42: EURUSD 0.53–1.00 (mean 0.71, below the 80 % warning),
  GBPUSD 0.40–1.00 (mean 0.86), USDCHF 0.59–0.99 (mean 0.81) — EM local optima; discussed
  honestly in phase 04.
- Tests (`tests/test_hmm.py`, 10): filtering vs brute force, causality, frame log-likelihood
  vs hmmlearn, naming rule, run length, score outputs + truncation invariance, train-only
  scaler, bundle round trip, saved-model sanity (diag > 0.8, 4 states, permutation),
  contract of the artifacts.

## v0.3.0 — phase-02: feature engine (2026-08-18)

- `src/fxradar/features.py`: `build_features(prices)` computes the base contract features per
  pair — `ret_1d` (log return), `vol_20`/`vol_60` (rolling sample std × √252, ddof=1),
  `vol_ratio` (5-day vol / vol_60, the "storm front"), `mom_20`, `rng_hl` (10-day mean of
  (high−low)/close), `corr_20`, `ret_5d_abs`. Strictly causal; first 60 rows per pair dropped
  as warm-up; no scaling (models own their scalers).
- `corr_20` — deliberate, documented readings of the spec: (a) returns are put on one sign
  convention before correlating (USDCHF negated via `config.USD_BASE_PAIRS`, so every column
  is foreign-currency-vs-USD; the literal un-flipped mean gives medians −0.07/+0.04/−0.71
  because the +/− legs cancel, the flipped one gives 0.75/0.64/0.71 — a comparable
  "dollar-factor strength" across pairs); (b) each of the two correlations is computed on the
  dates both pairs traded and as-of aligned backward onto the pair's own dates (a hole in one
  pair only freezes that leg); (c) an undefined (zero-variance) window yields NaN, never a
  stale value.
- CLI `python -m fxradar.features`: prices.parquet → `data/features.parquet` (16 660 rows ×
  10, 2005-03-28 → 2026-08-17), prints shape, rows per pair, date range and NaN report (0).
- Tests (`tests/test_features.py`, 12): contract schema/dtypes, no post-warm-up NaNs, toy
  constant series, hand-computed vol_20/vol_60/vol_ratio/mom_20/ret_1d/rng_hl/ret_5d_abs,
  corr_20 mean-of-two + sign convention + hole + zero-variance semantics, TRUNCATION
  INVARIANCE (drop last 30 rows per pair; `assert_frame_equal(check_exact=True)`), one-pair
  truncation, shifting-start drift check. Verified on the full real history for k = 1, 5, 30.

## v0.2.0 — phase-01: data loader (2026-08-18)

- `src/fxradar/data.py`: `download_prices` (yfinance `EURUSD=X`, `CHF=X`, `GBPUSD=X`; 3 attempts
  with 2s/4s backoff; tidy long format `date, pair, open, high, low, close`; trading days only,
  never forward-filled; the in-progress current-day bar is excluded so reruns are reproducible;
  fails loudly on an empty pair).
- `validate_against_ecb`: frankfurter (ECB reference rates), last 3 years, EURUSD + USDCHF —
  count, mean and max absolute % deviation; WARNING above 0.5 % mean, error above 2 %.
  Measured: ~0.2 % mean deviation (fixings vs. Yahoo's start-of-day "close").
- Corrupted-print filters (`clean_prices`): reverting single-day bad ticks, absurd highs/lows
  (reciprocal-quoted prints) and out-of-bounds prices are DROPPED and logged with a reason,
  never repaired or filled. Currently 9 bars: 6× EURUSD 2008, USDCHF 2009-02-06,
  EURUSD + GBPUSD 2012-01-27. Real shocks (SNB 2015-01-15, Brexit) are untouched — tested.
- Documented Yahoo quirks in the module docstring: close ≈ start-of-day snapshot (so ~100
  rows/pair have close outside [low, high]); a 17-trading-day EURUSD source hole in Aug 2008.
- `python -m fxradar.data` CLI: download → clean → validate → save `data/prices.parquet` +
  `reports/prices_overview.png`; prints rows/date range/largest gap per pair, dropped bars,
  and ECB stats.
- `src/fxradar/config.py`: pairs, tickers, plausible price bounds, split dates + embargo,
  artifact paths, filter thresholds, `DISCLAIMER`.
- Tests (`tests/test_data.py`, 22 tests, no network): contract schema/dtypes, monotonic dates,
  positive + plausible OHLC, no weekends, tidy/no-fill/as-of cutoff, retry backoff, every
  filter rule (incl. "SNB survives" and row-order invariance), ECB stats/warn/raise (mocked),
  parquet round trip, summary + plot. Fixture: `tests/fixtures/prices_sample.parquet`
  (Oct 2014 – Dec 2015, 981 rows).
- `matplotlib` added to requirements (static pngs for `reports/`).

## v0.1.0 — phase-00: scaffold (2026-08-18)

- Repository skeleton matching CLAUDE.md "Repository layout": `src/fxradar` package
  (src layout, installable via `pyproject.toml`), `pipelines/`, `app/` (Streamlit shell),
  `models/`, `data/`, `reports/`, `docs/`, `tests/`.
- Tooling: `Makefile` (`setup`, `test`, `lint`, `fmt`, `run`, `pipeline`), pinned
  `requirements.txt`, ruff + black configured in `pyproject.toml`.
- `.streamlit/config.toml` dark theme with the design-system colours.
- `tests/test_smoke.py`: every module imports; version asserted.
- App shell renders the title and the disclaimer "Educational tool. Not investment advice."
- No data, no models, no secrets yet.
