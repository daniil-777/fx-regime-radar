# Full-system audit — 2026-08-24

_Educational tool. Not investment advice._

Scope: ML forensics (leakage, fit windows, splits, claim reproduction) · backtest/strategy honesty ·
the answer engine and bounded search agent (phases 36–43) · Python + Rust engineering bar ·
user surfaces & web/mobile performance · the eval harness. Method: 8 hostile-reviewer audit passes,
every serious finding adversarially re-verified (21 confirmed, 0 refuted), fixes applied with
pinning tests, anything touching a published number handled as a public correction — never silently.

## What the audit VERIFIED as sound (the record holds)

- **No leakage found in the shipped models.** All base features are trailing-window
  (features.py); HMM outputs are filtered-only — the forward filter at hmm_model.py:87–104, and
  `predict_proba` appears in src/ only inside the docstring banning it. Scaler/HMM/state-naming fit
  on ≤ 2016-12-31 (asserted by tests); forecaster labels t+1..t+5 with final rows NaN; embargo
  rows on BOTH sides of BOTH boundaries verified on the committed artifacts (train max 2016-12-23,
  val 2017-01-09→2018-12-24, test min 2019-01-08, exactly 10 unused rows per gap per pair).
- **Published champion numbers reproduce.** PR-AUC 0.5479718…, Brier 0.1023151… from the committed
  model meta match the published 0.548 / 0.102. EURUSD regimes rescored from the saved bundle:
  0 regime mismatches over 5,544 rows, max prob diff 4.6e-15; truncation invariance reproduced
  bit-for-bit during the audit itself.
- **The ledger chain verifies**: `scripts/verify_ledger.py` → VALID, 21 rows, head matches
  `data/ledger_head.txt`.
- **Siren, BOCPD, conformal calibration, features_ext, CB features, treasury** all fit strictly
  inside their declared windows, with point-in-time discipline (publication lags, as-of joins,
  release-date keying) verified at file:line and covered by truncation tests.
- **The Rust wall holds**: bundle crosses as ONNX/JSON/YAML/parquet only; startup order is
  load → verify hashes → golden selftest → bind; ops/trace separation, CORS default-closed,
  webhook signing, kill switch under load — all test-pinned and green.

## Blockers / majors found, adversarially confirmed, and FIXED

| id | finding | fix |
|----|---------|-----|
| F2/ML-01 | The "frozen, scored once" conformal receipt was recomputed daily over a growing 2019→today window: README said n = 5,922, the artifact had drifted to 5,931. | Receipt window **sealed** (`frozen_through` in conformal params, per universe: fx 2026-08-10, g10/em 2026-08-13, crypto 2026-08-14). fx receipt regenerated via the documented path and again reads exactly the published n = 5,922, 91.6 % (other universes byte-stable). Seal-once logic added to the pipeline stage; pinning tests added. **Public correction note in CHANGELOG.** |
| F3/BT-01 | `stress.py`'s verdict template printed "**No strategy has a positive gross Sharpe**" whenever ANY breakeven was 0 — false (S2_meanrev gross +0.12, breakeven 0.1×), contradicting its own table in the committed report. | Template rewritten as data-driven `costs_verdict()` (test-pinned). Committed report corrected **with a visible correction note** (old wording, new wording, date, cause); all numbers untouched. A full regeneration was started, found to move published numbers (inputs gained trading days), and **reverted** — exactly the line the constitution draws. |
| F4 | README bolded "the breakeven cost multiplier is 0" while the artifact says 0.1× for S2. | README corrected to "0–0.1×" with S2 named. |
| AE-01 | The archive lane answered about **EUR/USD** when a covered non-major was named ("crisis days for the yen" → EUR/USD's history) — the unfixed sibling of the c368437 wrong-market class, alive in the archive room. | Canonical resolved market now threads into `archive::answer(…, named)`; named markets can never fall through to the EUR/USD default; regression tests added. |
| AE-02 | The runtime direction lint on LLM output was 14 exact words — "rising", "strengthen", "higher", "appreciate" all passed the constitutional gate. | List widened to 62 words (the narrate.py vocabulary + inflections), shared by the alert lint and the avatar output gate. |
| AE-04 | `replay_deterministic` omitted the planted-figure, uncovered-market and courtesy stages — the phase-43 replay-parity guarantee was broken for exactly the classes c368437 added. | All three pure stages ported into replay; `uncovered_refusal_text` extracted so live and replay produce identical text. |
| RUST-01 | `/avatar/brain` had no turn rate limit and no conversation-size cap — unbounded LLM spend per credential. | Per-conversation token-bucket rate limit (keyed credential+session), 4,000-char message cap, conversation truncated to the newest 32 messages. Load test updated: 429 is deliberate backpressure, not a dropped request. |
| SURF-01/ENG-01 | The daily cron rebuilt the static customer surface every run and then **discarded it** — commit globs omitted `public/`. | `public/` added to the daily commit glob. |
| EVAL-01 | HEAD failed its own eval gate: c368437 re-recorded fixtures without re-recording thresholds; `reports/eval_baseline.md` was stale. | Fixtures re-recorded against the frozen snapshot with the fixed brain (280/280, 0 errors); baseline + 79 floors re-recorded via the documented process; `--check` green: **no regression, no compliance leak**. |
| EVAL-02 | "100 % or the suite fails" was a comment; only the leak metric was enforced (compliance routing floors as low as 8 %). | Labels now tell the enforcement truth (comment + report heading). After the fixes, compliance routing is **100 % on direction, advice, planted-number, stale-context and out-of-scope** (injection 80 % — the two misses refuse as advice instead of direction: refused either way). |
| EVAL-03 | Four golden items demanded refusals for plainly in-scope questions (phase-38 carryovers that lost their stale-pack precondition); two planted-number items couldn't detect parroting. | Items re-authored: in-scope → `answer`; planted figures → `refuse_not_in_pack` with the planted number in `must_not_contain`. |
| EVAL-04 | "Programmatic but wrong" golds: `count:` refs counted the snapshot's 3 majors for 23-market questions (one ref didn't even match its own question). | The three poisoned golds dropped per the seeder's own rule — a missing expectation is honest, a wrong one poisons the metric. |
| EVAL-05 | Deleting the fixtures file made the CI gate pass vacuously. | `--check` now fails loudly when any recorded floor has no current measurement. |
| EVAL-06 | `refused:not_covered` (the c368437 label) scored as **answer**; any unknown refusal label would too. | Label mapped; unknown `refused:*` labels now score as an unknown refusal — visible either way, never silently "answered". |
| EVAL-07 | The recall@k column rendered "—" forever (key mismatch). | Fixed; the retrieval headline is visible again. |
| + | Out-of-scope questions were being "answered" by similarity cards (an Excel-formula question got a ledger card; a Swiss-tax question got the COVID episode; "ballpark vol tomorrow" got a 1y-vol caption). | Off-domain vocabulary added (split from metric vocabulary), out-of-scope screen now runs before the visual caption lane in live AND replay, and the not-in-pack refusal carries its own gate label. out_of_scope routing 50 % → **100 %**. |

Also fixed (minors): ML-02 embargo test now covers the val/test boundary too · ML-05 vacuous
low-confidence intent test made unconditional · ML-06 `build_labels` refuses unsorted input loudly
(+ explicit sorts in conformal) · ENG-04 socket-blocking conftest fixture (network in tests now
fails loudly) · AE-08 archive-miss refusal text no longer overstates coverage ("monthly counts for
every market" → the truth) · SURF-04 Overview live-API cache got a TTL (was cached forever) ·
SURF-08 touch targets raised to the 44 px floor · black formatting on tools/screenshot.py.

**Eval scoreboard, before → after (routing):** direction 8→100 · advice 10→100 · injection 40→80 ·
planted-number 33→100 · stale-context 60→100 · out-of-scope 50→100 · no-visual 53→82 ·
multi-turn 76→86 · multi-hop 81→88 · causal 73→82 · comparative 82→88 · today 90→91.
"No banned words" stayed 100 % everywhere throughout.

## Environment repairs (the folder move's casualties — audit-00)

- The venv died as predicted (editable `.pth` and console-script shebangs pointed at
  `~/Downloads/fx-regime-radar 2`): repointed; suite went from un-collectable to green.
- A **stale `fxradar-serve` from a previous day was still holding :8090** with open+advice on —
  every early probe hit the old binary (the repo's own documented trap). Killed.
- The utoipa-swagger-ui build cache embedded pre-move paths → `/docs/` 404 in debug builds; cleaned.
- Zero stale absolute paths in tracked files; git fsck clean; ledger chain verifies.

## Flagged for owner decision (NOT applied — each would change behavior, a published number, or policy)

1. **F1 — the "frozen test" is a moving population across phases**: the 2019+ window has been
   scored by the champion (n=5,922 receipt), model-lab engines, and challengers at different data
   cuts. Decide: freeze one canonical test window for all future scorings, and add a
   "population windows" note to README Results.
2. **AE-03 — with ANTHROPIC_API_KEY set, the LLM outranks packs/FAQ/market templates**, inverting
   the phase-40/42 precedence the keyless path (and the whole eval) measures. Decide: reorder the
   ladder (deterministic first, LLM for the remainder) or record that production is keyless.
3. **AE-05 — the phase-37 scenario engine does not exist**, yet scenario questions are exempted
   from the direction guard on the claim that it does. Decide: build the deterministic scenario
   arithmetic or remove the exemption + claim.
4. **RUST-02/AE-11 — open mode (`FXRADAR_AVATAR_OPEN=1`) lets ungrounded LLM numbers through as
   "annotate-only"**; rule 4's written amendment covers the advice flag, not this. Off by default,
   direction lint still constitutional. Decide: amend CLAUDE.md rule 4 or restrict the exemption.
   Related: ENG-09 — `make avatar` (dev) enables OPEN+ADVICE unconditionally.
5. **BT-03 — the backtest cost model fills missing vol_20 with the full-sample median** (future
   data inside the engine; negligible in practice, but rule-1-adjacent). Fixing changes
   backtests.parquet on next regeneration → needs a versioned correction.
6. **AE-07 — "what did you say in 2015?" answers from tonight's rebuilt history, not the sealed
   ledger**; no logbook shape reads sealed rows by date. Decide: add the sealed-logbook shape.
7. **RUST-06 — alert webhooks accept any http(s) URL including loopback/cloud-metadata (SSRF)**;
   RUST-04/05 — blocking I/O + inference on the async runtime; RUST-07 — session tokens stored in
   plaintext (API keys are hashed); RUST-11 — length-leaking constant-time compare.
8. **ENG-05 — requirements pins are ranges, not `==`** (CI environment can drift daily);
   ENG-02 — `stage_write` is not atomic (local-crash blast radius only; CI can't commit a partial
   state). ENG-03 — bocpd/conformal first-run fits happen mid-pipeline (documented, train/val-only).
9. **Version drift** — `fxradar.__version__` 2.8.0 vs pyproject 2.10.0 vs Rust crate 2.11.0 vs
   tags v2.40.1. Pick one truth.
10. **EVAL-08/09/10** — the promised nightly real-model eval lane doesn't exist (the LLM path has
    never been scored); board composition beyond card #1 is unmeasured; injection family lacks
    multi-turn/URL-smuggling/poisoned-retrieval cases. AE-09 — torn-read guard covers archive.json
    only; AE-10 — prompt-caching is scaffolding (no cache_control sent).
11. **SURF-02/03/05/06/09** — avatar.html exempt from budget/a11y checks; Advisor page imports the
    HMM stack in-app (1.55 s cold); one static page shows the same market twice with different
    numbers; static Proof page labels the frozen TEST Brier "(validation)" and drops the base-rate
    comparison (rule-3-adjacent); trust strip on 2 of 15 app views. SURF-07 — no static
    direction-word lint over public/ + README (runtime gates only). F5 — README's "every ledger row
    since 2026-08-18 carries the conformal band" overstates the 9 challenger rows.
12. **Unpushed work** — local main is ahead of origin (the public record lacks the latest fixes).
    Push when ready.

## The three-reader verdict

**The recruiter** sees a system whose headline numbers reproduce to 1e-6 from committed artifacts,
whose test suite (377+ Python, 81+ Rust) is green from a cold clone, and whose one drifting
"frozen" number is now sealed with the drift documented in the open. **The quant** can no longer
find the wrong-market answer in the archive room, an unfrozen frozen set, a false sentence in the
stress report, or an eval that couldn't fail — what they will find is every remaining weakness
listed above, in writing. **The treasurer** gets refusals that are actually refusals (out-of-scope
routing 100 %), advice only when the flag is deliberately on and only voiced from the deterministic
table, and a disclaimer on every surface.
