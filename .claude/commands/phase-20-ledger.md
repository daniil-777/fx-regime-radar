---
description: Phase 20 — live forward-test ledger + drift monitor + public proof (next minor tag)
---

Read CLAUDE.md golden rules first. This starts the clock on the one asset
nobody can fake: a tamper-evident live track record. Run before everything
else — every unrecorded day is proof lost forever.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled from your phase files: daily orchestrator `pipelines/run_daily.py`
(register-a-step pattern); scored outputs in `data/regimes.parquet` (regime,
regime_prob, change_risk_5d, top_drivers, anomaly_score, anomaly_pct per pair);
features `data/features.parquet` (9 continuous features); H = 5 trading days
with the 5-day embargo convention; saved models under `models/`; daily GitHub
Action already commits `data/` at 06:00 UTC. Verify this still matches, report
any drift, and WAIT for my confirmation.

## Task
Append-only hash-chained ledger, a maturity-aware scorer, a drift monitor
with a model-stale flag, and a public proof page: "Don't trust us. Verify."

## Requirements
1. `src/fxradar/ledger.py`: row = run_date, pair, model_versions (git SHA +
   hmm/forecaster/siren semvers from the artifacts), regime, four filtered
   probabilities, change_risk_5d, anomaly_pct, prev_hash, row_hash =
   sha256(prev_hash + canonical sorted-key JSON). `append_forecast()` verifies
   the whole chain from genesis, then appends to `data/ledger.parquet`.
   Idempotent per (run_date, pair). Corrections are NEW rows with a
   correction flag referencing the original row_hash — never edits.
2. Register as the LAST run_daily step (after narration), one line, per the
   existing pattern. Also write `data/ledger_head.txt` (head hash + date):
   the existing daily Action commit of data/ then timestamps the chain head
   on GitHub — external notarization for free. Confirm the workflow's commit
   globs include both files.
3. `src/fxradar/score_ledger.py`: score only matured rows (run_date + 5
   trading days ≤ today) against realized regime changes from
   regimes_base.parquet; live Brier and PR-AUC, segmented by model_versions
   so the monthly refit path never pollutes the record; write
   `reports/live_scoreboard.md` + json. README Results section gains:
   "Since <deploy>: live PR-AUC x / Brier y on N unseen days, vs frozen test
   <the phase-07 numbers>."
4. `src/fxradar/drift.py`: PSI per feature (10 quantile bins fit on train ≤
   2016; 0.1 watch / 0.25 drifted), KS train-era vs last 60 days, and mean
   per-day filtered log-likelihood of the last 60 days under each pair's
   saved HMM vs its train-era distribution → `data/status.json` with
   model_stale flag; badge in the dashboard header next to "Data through".
5. Public proof: `scripts/verify_ledger.py` — stdlib only, ≤40 lines, prints
   VALID/BROKEN + head hash on a fresh clone. New app page
   `app/pages/2_Proof.py` (artifacts-only, cached like the rest): scoreboard,
   drift status, ledger download, the three-line verify instructions.
6. Tests: tamper a middle row → verify fails; double-run same day → one row
   per pair; scorer refuses unmatured rows; chain verifies from genesis;
   drift fires on synthetic shifted fixtures. No network in pytest.

## Do not
Never rewrite or migrate existing rows. No backfilling pre-deploy dates. No
scoring before maturity. No new dependencies (hashlib is stdlib).

## Verify
- Three simulated daily runs; chain verifies; tamper test fails loudly.
- verify_ledger.py on a fresh clone; ledger_head.txt in the Action's commit.
- README live table renders; proof page shown. `make test` green including
  the untouched truncation-invariance test.
- CHANGELOG, commit `phase-20: live ledger + drift + proof`, next minor tag.

## Teach me
Explain: why ex-ante sealed forecasts beat any backtest; what the hash chain
guarantees and what it doesn't; PSI in one paragraph; why the scoreboard
segments by model version. Quiz me: (1) what does the GitHub commit add that
local hashing can't? (2) monthly refit lands — what happens to the record?
Critique my answers.
