---
description: Audit 04 — close-out: adjudicate flagged findings, apply approved fixes with correction notes, seal v2.6.1 (audit series — final tag)
---

Read CLAUDE.md golden rules first. Audits 00–03 produced a findings ledger
with a hard split: mechanical issues were fixed as found; anything that
changes model behavior, a published number, or a committed artifact was
flagged and left alone. This session adjudicates the flagged items WITH me,
applies only what I approve, publishes corrections honestly rather than
silently, and seals the audited baseline. Corrections handled in the open
are a credibility asset; corrections handled quietly are a scandal
deferred.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: `reports/audit_01_ml_findings.md` is the findings ledger,
updated through audit-03, with severity and the Y/N "changes a published
number or committed artifact" column; `docs/STATE.md` carries the baseline
numbers (test count, CI time, loader timings, orb budget); commits
`audit-00` … `audit-03` exist; the live ledger (phase 20) may or may not
have started in the meantime — check for `data/ledger.parquet` and adapt:
if it exists, its rows are IMMUTABLE and any model-touching fix requires a
model_versions bump so the record stays segmented. Verify, report drift,
WAIT.

## Requirements
A. Adjudication (the WAIT is the point)
1. Present every open finding one at a time: what it is, which golden rule
   it stresses, the exact proposed fix, the blast radius (which artifacts,
   reports, and published numbers change), and a recommendation. I choose:
   fix now / defer to IDEAS.md with a dated line / accept as-is with a
   one-line rationale recorded in the ledger. Nothing is applied before
   its decision.

B. Application discipline
2. Each approved fix lands with a pinning test written FIRST, then the
   minimal change, then the regeneration of ONLY the affected artifacts via
   their documented paths (never hand edits). If a published number
   changes: the affected report keeps the history visible — old value, new
   value, date, one-sentence cause — and the README Results section gains
   the same note if it quoted the number. If any model file changes: bump
   its semver, rebuild the export bundle, and rerun the Rust selftest; and
   if the live ledger is running, confirm the new model_versions string
   appears on the next row so live scoring stays segmented.
3. Re-run the audit-01 determinism proof after all fixes: double-run,
   byte-identical, shown.

C. Seal
4. Full gate: `make lint` (now including lint-direction), `make test`,
   `cargo test`, `cargo clippy -- -D warnings`, bundle selftest, one full
   `make pipeline`, app boot. All green, timings recorded in STATE.md.
5. `reports/AUDIT_CLOSEOUT.md`, one page: findings counted by severity;
   fixed / deferred / accepted; every public correction listed; the
   three-reader verdict written as three short paragraphs (what the
   recruiter now sees, what the quant now cannot find, what the treasurer
   now gets); and the closing line naming the next action — if the live
   ledger is still not running, that line is "run phase-20 today", in bold,
   because every unsealed day is evidence lost forever.
6. Update STATE.md and CHANGELOG (audit series summarized in one entry);
   commit `audit-04: close-out`, tag `v2.6.1 — audited baseline`. The tag
   is a patch, deliberately: minor tags are reserved for feature phases,
   and the next minor belongs to the ledger.

## Do not
No fixes beyond the adjudicated list — new discoveries mid-session go to
the ledger for a later pass unless they are blockers, in which case stop
and present. No silent number changes anywhere. No editing or rewriting
ledger rows if phase 20 is live. No scope creep into phases 19–45. No
history rewriting; the audit commits stand as they are.

## Verify
- Every ledger row shows a decision and an outcome; zero rows left open.
- All correction notes shown to me in their final rendered form.
- The full gate output green; the determinism re-proof shown.
- AUDIT_CLOSEOUT.md read to me in full; tag `v2.6.1` exists.

## Teach me
Explain: why a public correction note makes the record stronger rather than
weaker, and what model_versions segmentation protects the moment a fix
touches a model with a live ledger running. Then quiz me: (1) a major
finding surfaces DURING this close-out — walk the decision tree; (2) an
investor asks "how do I know these audit commits didn't quietly improve the
track record?" — give the two-sentence answer this repo makes true.
Critique my answers.
