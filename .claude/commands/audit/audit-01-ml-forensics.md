---
description: Audit 01 — ML forensics: leakage hunt, determinism proof, claim reproduction, adversarial tests (audit series — tag v2.6.1 at close-out)
---

Read CLAUDE.md golden rules first. This session wears the researcher hat and
attacks phases 01–18 the way a hostile quant reviewer would: assume there is a
leak, a double shift, or an unreproducible number somewhere, and go find it.
Prerequisite: audit-00 is committed and its baseline is green. The prime
directive of this session: FINDING problems and FIXING them are separated —
mechanical bugs get fixed with a pinning test; anything that would change a
published number or a committed artifact gets flagged and STOPS for my
decision, because those numbers are the public record.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: splits train ≤ 2016-12-31, val 2017–2018, test 2019+, 5-trading-day
embargo at each boundary; seed 42 everywhere; HMM = 4-state GaussianHMM, full
covariance, inputs [ret_1d, vol_20, mom_20], scaler fit on train only,
hand-written causal forward filter (predict_proba is banned for outputs);
frozen state→name mapping from train stats; forecaster = pooled XGBClassifier
(max_depth 3, lr 0.04, early stopping on val, scale_pos_weight from TRAIN),
labels = regime change within t+1..t+5, threshold chosen on VAL for recall
≥ 0.6; published frozen-test numbers in the project docs: PR-AUC 0.548,
Brier 0.102 — confirm `reports/forecaster_eval.md` states the same (a mismatch
between docs and repo is itself a top finding); siren = MLPRegressor (8,3,8),
scaler fit on TRAIN calm days with regime_prob > 0.7, anomaly_pct = percentile
vs the TRAIN calm error distribution, nearest neighbor excludes ±10 days,
validated on 2015-01-15 USDCHF; backtest engine owns the one-day lag
internally, cost = base_bps + vol_mult·vol_20 on turnover, foresight test
exists; strategies S1/S2/S3 + overlay (scale by (1 − change_risk_5d) when
risk > 0.3, flat when anomaly_pct > 98, ~10% vol targeting, 2x cap);
stress lab reports breakeven cost multipliers; arcade scores Brier with a
server-side lock-before-reveal rule; export bundle carries 300 golden vectors
with recorded ONNX parity diffs. Verify each fact against the code (exact
file:line), report drift, WAIT.

## Requirements
A. Determinism — same inputs, same bytes
1. Run the scoring pipeline twice on identical inputs; `sha256sum` every file
   it writes; assert byte-identical, except fields that are timestamps by
   design — list each such field and justify it in one line. Expected
   outcome: identical. Any diff is a finding (unpinned dependency, unsorted
   iteration, unseeded call), not something to paper over.
2. Rebuild features from the committed prices.parquet and byte-compare
   against the committed features.parquet. If they differ, diagnose WHY
   (library version drift is the usual suspect) and flag — do NOT overwrite
   the committed artifact.

B. Causality — the leakage hunt
3. Enumerate every call site of `predict_proba`, `score_samples`,
   `decode`, `predict` on the HMM, and any `.shift(-`, `pct_change(-`,
   `rolling` with `center=True`, or negative indexing into the future,
   across `src/`. Each hit is proven output-safe (test or train-time-only)
   or is a finding with file:line.
4. One new parametrized test `tests/test_truncation_everything.py`: build on
   the full fixture and on the fixture minus its last 30 rows; assert the
   overlap bit-for-bit equal for (a) features, (b) all five HMM-derived
   columns (regime, regime_prob, hmm_entropy, days_in_regime, vol_trend),
   (c) the assembled forecaster feature matrix, (d) siren anomaly_score and
   anomaly_pct, (e) backtest engine outputs for a fixed toy position series.
   The two existing sacred tests are NOT edited — this test extends coverage
   beside them.
5. Fit-window audit: list EVERY fitted object in the repo (HMM scaler, HMM
   itself, forecaster, siren scaler, siren, the anomaly_pct reference
   distribution, the naive vol rule's trailing percentile, any label
   encoders) with the exact date range each was fit on, as a table. Each row
   gets an asserting test if one is missing; anomaly_pct's reference must be
   the TRAIN calm distribution, and the vol rule's percentile must be
   trailing, not full-sample.

C. Labels, splits, embargo
6. Recompute forecaster labels independently inside a test from
   regimes_base.parquet and assert equality with the training labels; assert
   the final 5 rows per pair are dropped; assert the embargo gap of ≥ 5
   trading days exists per pair at BOTH boundaries (strengthen the existing
   test if it checks only one).
7. Grep for any `.fit(` receiving data outside its declared window; confirm
   no code path lets val or test rows into training, and that early stopping
   reads val only.

D. Claim reproduction — the record must regenerate
8. From the SAVED model files only (no retraining, no refitting, no new
   variants), re-run the frozen-test evaluation exactly as phase 07 defined
   it and assert PR-AUC and Brier equal the numbers printed in
   `reports/forecaster_eval.md` to 1e-6. State in a comment: this is
   reproduction of the one recorded scoring, permitted by the
   reproducibility rule; it is not a second scoring, and nothing may be
   tuned in response to anything seen here.
9. Threshold provenance: recompute the val-chosen threshold from the saved
   model and the recall ≥ 0.6 rule; assert it equals the threshold in use.
10. Reproduce from committed artifacts: the siren top-15 table including
    2015-01-15 USDCHF; the strategy_eval headline metrics; the stress lab's
    breakeven multipliers. Tolerance 0 where the inputs are committed. Every
    number that fails to reproduce goes in the findings ledger with severity
    "blocker" — an unreproducible published number is the worst defect this
    project can contain.

E. The engine cannot be fooled
11. Confirm the foresight test's assertion is sharp (cheating Sharpe huge
    without lag, |Sharpe| below a stated small bound with lag) — record the
    actual bounds. Then hunt the double-shift bug: grep strategies.py and
    stress.py for any manual `.shift(` on positions; the lag lives in the
    engine ONLY. A second shift means every strategy trades a day late and
    every published strategy number is wrong — if found, this is a blocker
    finding, not an inline fix.
12. Two new engine tests: entry cost charged exactly once for a
    buy-and-hold toy (hand-computed to the cent); explicit, documented NaN
    policy for positions (assert it raises or fills — whichever the code
    intends — rather than silently propagating).
13. Overlay tests exist and pass: flat when anomaly_pct > 98; vol targeting
    lands 10% ± 2 pp on train; leverage never exceeds 2.0 anywhere in the
    output frame (add the max-abs assertion if missing).

F. Findings ledger
14. `reports/audit_01_ml_findings.md`: one row per finding — id, severity
    (blocker / major / minor), file:line, golden rule stressed, proposed
    fix, and the column "changes a published number or committed artifact?
    Y/N". Fix inline, each with a pinning test, ONLY rows marked N. Every Y
    row: stop, present, WAIT.

## Do not
Never retrain, retune, or fit any new model variant. Never let anything
touch 2019+ as an input to a choice. Never regenerate a committed artifact
to make a test pass. Never weaken a tolerance or edit the two sacred tests.
No new dependencies. No fixes to Y-flagged findings in this session.

## Verify
- Full suite green including every new test; count of new tests stated.
- The double-run hash comparison and the claim-reproduction assertions shown
  in the transcript.
- The fit-window table and the findings ledger read to me row by row.
- CHANGELOG; commit `audit-01: ml forensics (+N tests, M findings)`. No tag.

## Teach me
Explain: the difference between reproducing a frozen-test number and scoring
the test a second time, and why one is mandatory while the other is banned;
and the double-shift bug — how a correct engine plus a "careful" caller
produces a subtly wrong backtest. Then quiz me: (1) feature regeneration
differs from the committed parquet by 1e-12 in three cells — ship the
regenerated file, keep the old one, or investigate, and in what order?
(2) which single finding category in this session would force a public
correction note rather than a quiet fix, and why? Critique my answers.
