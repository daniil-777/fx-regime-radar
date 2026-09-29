---
description: Audit 02 — engineering bar: lint truth, contracts, test teeth, Rust discipline, CI budget (audit series — tag v2.6.1 at close-out)
---

Read CLAUDE.md golden rules first. This session wears the engineer hat and
holds every line of Python and Rust to the professional bar: boring, typed,
contracted, tested, deterministic. Unlike audit-01, this session FIXES
mechanically as it goes — style, hygiene, and missing tests are corrected
inline — but the same hard line holds: nothing that changes model behavior,
published numbers, or committed artifacts. Prerequisite: audit-00 and
audit-01 are committed.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: the bar is CLAUDE.md plus the engineering-standards file — ruff
and black clean with zero suppressions, type hints on every public
signature, docstrings on public functions, no notebooks, no dead code, no
TODO without a dated IDEAS.md line, pinned dependencies, no network in
pytest, fixtures small/committed/dated; Rust: clippy clean with no allow
attributes, no unwrap/expect in library code, thiserror enums, tracing not
println, nothing on the serve path can panic; the wall crosses only as
JSON/ONNX/YAML/parquet (joblib is legal on the Python side, illegal in the
bundle); CI is sklearn-only and about five minutes; audit-01 left a findings
ledger at `reports/audit_01_ml_findings.md` whose N-flagged leftovers and
missing-test notes belong to this session. Verify, report drift, WAIT.

## Requirements
A. Python truth pass
1. Inventory every `# noqa`, `# type: ignore`, `# pylint`, and ruff/black
   config exclusion. Each one is removed by fixing the underlying issue, or
   kept with a one-line WHY comment — target: zero unexplained suppressions.
2. Type hints: a small stdlib AST script (no new deps) lists every public
   function or method in `src/` missing parameter or return annotations;
   drive the list to zero. Same script checks each public function has a
   docstring; missing ones get a WHY-focused line, not a restatement.
3. Dead-code and hygiene sweep: commented-out blocks deleted; `print(` in
   `src/` replaced with logging (the CLI `__main__` summaries may print —
   note the exception once); every TODO moved to IDEAS.md with today's date
   or resolved; no notebook files anywhere.
4. pandas discipline spot-audit on the three hot modules (features,
   forecaster, backtest): no mutation of caller frames (`.copy()` where
   returned frames derive from inputs), explicit dtypes at file boundaries,
   no row-wise `apply` where a vectorized form exists — fix what is safe,
   flag what would alter outputs.

B. Dependencies and test hygiene
5. `requirements.txt` pins are exact (`==`), `pip check` clean, and no heavy
   library (torch, transformers, umap, embeddings) appears — expected
   already true; prove it.
6. Add `tests/conftest.py` with a socket-blocking fixture (stdlib only) so
   ANY network call inside pytest fails loudly; run the suite; fix or flag
   every test that trips it. Fixtures are checked: each is small, committed,
   and carries a dated comment naming its source.
7. Every DESIGNED fallback has a test that forces it to fire: the narrator's
   missing-key template path (exists per phase 09 — verify assertions are
   sharp: exactly three sentences, regime name and risk figure present,
   `source: "template"`); the pipeline's failed-fetch path (artifacts stay
   at last good state, nonzero exit); the export loader's manifest-hash
   mismatch path. Add whichever is missing.

C. Contracts
8. Bundle purity test: assert the newest `models/bundle_v*/` contains only
   .json, .onnx, .yaml, .parquet files, and that manifest.json's hashes
   verify against the files. Assert every JSON the repo writes uses sorted
   keys (canonical form) — fix writers that don't, flag if the fix would
   change a committed artifact's bytes.
9. Schema tests exist for each parquet contract (prices, features,
   regimes_base, regimes, backtests): column names, dtypes, and
   monotone-increasing dates per pair. Add the missing ones. Tests assert
   contracts, never implementation details — while here, rewrite any test
   that pokes at private internals so a faithful refactor would still pass.

D. Rust discipline
10. `grep -rn "#\[allow"` in `rust/` → zero in non-test code, or each
    justified and removed where possible. `grep -rn "unwrap()\|expect("` in
    library code (tests and the selftest binary excluded) → drive to zero
    via proper error propagation. `cargo clippy -- -D warnings` clean.
11. Confirm handlers do no model math and no blocking I/O; confirm the
    startup order is load → verify hashes → golden selftest → bind, and that
    `--skip-selftest` still logs its loud warning. Confirm serde structs
    mirror the bundle field-for-field (compare against
    docs/bundle_format.md; fix the DOC if the code is right).

E. CI budget and coverage of the audit
12. Time the full CI-equivalent locally (lint + pytest + cargo test +
    selftest); record the number. If over ~5 minutes, find the slowest test
    with `--durations=10` and flag (never delete) candidates. Confirm the
    workflow's commit globs still match every artifact the pipeline writes.
13. Close out every N-flagged item and missing-test note inherited from
    audit-01; update its ledger status column in place.

## Do not
No behavior changes to any model, feature, or artifact — if a cleanup would
alter bytes of a committed output, it becomes a flagged finding for
audit-04. No new runtime dependencies. No refactors for taste — only
refactors that remove a rule violation. No weakening or deleting any test.
No touching phases 19–45.

## Verify
- `make lint` green with the suppression inventory at zero-or-justified;
  the AST script reports zero missing hints/docstrings; suite green with
  the socket blocker active; `cargo clippy -- -D warnings` green.
- Bundle purity and schema tests shown passing; CI timing number recorded
  in STATE.md.
- Updated findings ledger read to me.
- CHANGELOG; commit `audit-02: engineering pass (+N tests)`. No tag.

## Teach me
Explain: why "tests assert contracts, not implementations" is what makes
refactoring cheap, with one concrete before/after from this session; and why
a socket-blocking conftest is worth more than a code-review promise. Then
quiz me: (1) a reviewer finds one `unwrap()` in a Rust handler — what is the
worst-case production story it enables, given this service's startup gate?
(2) name the one suppression comment you would ever accept permanently in
this repo, and defend it. Critique my answers.
